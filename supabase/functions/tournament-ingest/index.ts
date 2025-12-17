import { serve } from "https://deno.land/std@0.205.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.45.6";

type JsonRecord = Record<string, unknown>;

type PrizeItem = {
  amount?: number | string;
  token?: string;
  text?: string;
  usd_value?: number | string;
};

const API_BASE = "https://api.splinterlands.com";
const DEFAULT_MAX_AGE_DAYS = 3;
const DEFAULT_MAX_TOURNAMENTS = 200;
const EVENT_BATCH = 200;
const RESULT_BATCH = 500;
const FETCH_TIMEOUT_MS = 20_000;

function parseDate(value: unknown): Date | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(String(value));
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  return parsed;
}

function toInt(value: unknown): number | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const num = Number(value);
  if (Number.isNaN(num)) {
    return null;
  }
  return Math.trunc(num);
}

function normalizePrizeItem(item: unknown): PrizeItem | null {
  if (!item || typeof item !== "object") {
    return null;
  }
  const record = item as JsonRecord;
  const amount = record.amount ?? record.qty ?? record.value;
  const token = record.token ?? record.type;
  const text = record.text;
  const usdValue = record.usd_value;
  if (amount === undefined && token === undefined && text === undefined) {
    return null;
  }
  return {
    amount: amount as number | string | undefined,
    token: token ? String(token) : undefined,
    text: text ? String(text) : undefined,
    usd_value: usdValue as number | string | undefined,
  };
}

function parsePrizes(player: JsonRecord, payouts: unknown): { prizeTokens: PrizeItem[] | null; prizeText: string | null } {
  const prizeTokens: PrizeItem[] = [];
  const prizeTextParts: string[] = [];

  const directPrize =
    player.ext_prize_info ??
    player.prizes ??
    player.prize ??
    player.player_prize;

  if (Array.isArray(directPrize)) {
    for (const item of directPrize) {
      const normalized = normalizePrizeItem(item);
      if (!normalized) {
        continue;
      }
      prizeTokens.push(normalized);
      const text = normalized.text ?? `${normalized.amount ?? ""} ${normalized.token ?? ""}`.trim();
      if (text) {
        prizeTextParts.push(text);
      }
    }
  } else if (directPrize && typeof directPrize === "object") {
    const normalized = normalizePrizeItem(directPrize);
    if (normalized) {
      prizeTokens.push(normalized);
      const text = normalized.text ?? `${normalized.amount ?? ""} ${normalized.token ?? ""}`.trim();
      if (text) {
        prizeTextParts.push(text);
      }
    }
  } else if (typeof directPrize === "string") {
    prizeTextParts.push(directPrize);
  }

  const finish = toInt(player.finish);
  if (Array.isArray(payouts) && finish !== null) {
    for (const payout of payouts) {
      if (!payout || typeof payout !== "object") {
        continue;
      }
      const record = payout as JsonRecord;
      const startPlace = toInt(record.start_place);
      const endPlace = toInt(record.end_place);
      if (startPlace === null || endPlace === null || finish < startPlace || finish > endPlace) {
        continue;
      }
      const items = Array.isArray(record.items) ? record.items : [];
      for (const item of items) {
        const normalized = normalizePrizeItem(item);
        if (!normalized) {
          continue;
        }
        prizeTokens.push(normalized);
        const text = normalized.text ?? `${normalized.amount ?? ""} ${normalized.token ?? ""}`.trim();
        if (text) {
          prizeTextParts.push(text);
        }
      }
    }
  }

  const uniqueText = Array.from(new Set(prizeTextParts)).filter(Boolean);
  return {
    prizeTokens: prizeTokens.length ? prizeTokens : null,
    prizeText: uniqueText.length ? uniqueText.join("; ") : null,
  };
}

function buildQuery(params: Record<string, string>): string {
  const search = new URLSearchParams(params);
  return search.toString();
}

function extractAuthToken(req: Request): string | null {
  const authHeader = req.headers.get("authorization") ?? req.headers.get("Authorization");
  if (authHeader) {
    const match = authHeader.match(/^Bearer\\s+(.+)$/i);
    if (match) {
      return match[1].trim();
    }
  }
  const apiKey = req.headers.get("apikey");
  return apiKey ? apiKey.trim() : null;
}

async function fetchJson(url: string, params?: Record<string, string>): Promise<unknown> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  const fullUrl = params ? `${url}?${buildQuery(params)}` : url;
  try {
    const resp = await fetch(fullUrl, {
      headers: { accept: "application/json" },
      signal: controller.signal,
    });
    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
    }
    return await resp.json();
  } finally {
    clearTimeout(timeout);
  }
}

function getPayouts(record: JsonRecord | null): unknown {
  if (!record) {
    return null;
  }
  const data = record.data as JsonRecord | undefined;
  const prizesFromData = data?.prizes as JsonRecord | undefined;
  if (prizesFromData?.payouts !== undefined) {
    return prizesFromData.payouts;
  }
  const prizes = record.prizes as JsonRecord | undefined;
  if (prizes?.payouts !== undefined) {
    return prizes.payouts;
  }
  return null;
}

async function upsertInChunks(
  client: ReturnType<typeof createClient>,
  table: string,
  rows: JsonRecord[],
  chunkSize: number,
  onConflict: string,
): Promise<void> {
  for (let i = 0; i < rows.length; i += chunkSize) {
    const chunk = rows.slice(i, i + chunkSize);
    const { error } = await client.from(table).upsert(chunk, { onConflict });
    if (error) {
      throw new Error(`Upsert failed for ${table}: ${error.message}`);
    }
  }
}

async function readPayload(req: Request): Promise<JsonRecord> {
  if (!req.body) {
    return {};
  }
  try {
    const text = await req.text();
    if (!text.trim()) {
      return {};
    }
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === "object") {
      return parsed as JsonRecord;
    }
  } catch (_err) {
    return {};
  }
  return {};
}

serve(async (req) => {
  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const authToken = extractAuthToken(req);
  if (!supabaseUrl || !authToken) {
    return new Response(
      JSON.stringify({ error: "SUPABASE_URL and Authorization header are required" }),
      { status: 500, headers: { "Content-Type": "application/json" } },
    );
  }

  const payload = await readPayload(req);
  const organizer = typeof payload.organizer === "string" && payload.organizer.trim()
    ? payload.organizer.trim()
    : null;
  const maxAgeRaw = Number(payload.max_age_days);
  const maxTournamentsRaw = Number(payload.max_tournaments);
  const maxAgeDays = Number.isFinite(maxAgeRaw) ? Math.max(1, maxAgeRaw) : DEFAULT_MAX_AGE_DAYS;
  const maxTournaments = Number.isFinite(maxTournamentsRaw)
    ? Math.max(1, maxTournamentsRaw)
    : DEFAULT_MAX_TOURNAMENTS;

  const supabase = createClient(supabaseUrl, authToken, {
    auth: { persistSession: false },
  });

  const now = new Date();
  const nowIso = now.toISOString();
  const cutoff = new Date(now.getTime() - maxAgeDays * 24 * 60 * 60 * 1000);

  let organizers: string[] = [];
  if (organizer) {
    organizers = [organizer];
  } else {
    const { data, error } = await supabase
      .from("tournament_ingest_organizers")
      .select("username")
      .eq("active", true);
    if (error) {
      return new Response(JSON.stringify({ error: error.message }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    }
    organizers = (data ?? []).map((row) => String(row.username)).filter(Boolean);
  }

  const results: JsonRecord[] = [];

  for (const org of organizers) {
    const stateBase: JsonRecord = {
      organizer: org,
      last_run_at: nowIso,
      last_window_days: maxAgeDays,
      updated_at: nowIso,
    };
    await supabase.from("tournament_ingest_state").upsert(stateBase, { onConflict: "organizer" });

    try {
      const listResp = await fetchJson(`${API_BASE}/tournaments/mine`, { username: org });
      if (!Array.isArray(listResp)) {
        throw new Error(`Unexpected response for organizer ${org}`);
      }

      const eventRows: JsonRecord[] = [];
      const resultRows: JsonRecord[] = [];
      let processed = 0;

      for (const item of listResp) {
        if (processed >= maxTournaments) {
          break;
        }
        if (!item || typeof item !== "object") {
          continue;
        }
        const itemRecord = item as JsonRecord;
        const tid = itemRecord.id ? String(itemRecord.id) : "";
        if (!tid) {
          continue;
        }

        const listStart = parseDate(itemRecord.start_date);
        if (listStart && listStart < cutoff) {
          continue;
        }

        const detailResp = (await fetchJson(`${API_BASE}/tournaments/find`, {
          id: tid,
          username: org,
        })) as JsonRecord | null;

        const detailRecord = detailResp ?? {};
        const startDate = parseDate(detailRecord.start_date ?? itemRecord.start_date);
        if (startDate && startDate < cutoff) {
          continue;
        }

        const status =
          (detailRecord.status as string | undefined) ??
          (detailRecord.current_round as string | undefined) ??
          (itemRecord.status as string | undefined);
        const entrants =
          detailRecord.players_registered ??
          detailRecord.num_players ??
          itemRecord.players_registered ??
          null;
        const payoutList = getPayouts(detailRecord) ?? getPayouts(itemRecord) ?? null;
        const allowedCards =
          (detailRecord.data as JsonRecord | undefined)?.allowed_cards ??
          (itemRecord.data as JsonRecord | undefined)?.allowed_cards ??
          null;

        eventRows.push({
          tournament_id: tid,
          organizer: org,
          name: itemRecord.name ?? detailRecord.name ?? tid,
          start_date: startDate ? startDate.toISOString() : null,
          status,
          entrants,
          entry_fee_token: null,
          entry_fee_amount: null,
          payouts: payoutList,
          allowed_cards: allowedCards,
          raw_list: itemRecord,
          raw_detail: detailRecord,
          updated_at: nowIso,
        });

        const players = Array.isArray(detailRecord.players) ? detailRecord.players : [];
        if (players.length) {
          for (const player of players) {
            if (!player || typeof player !== "object") {
              continue;
            }
            const playerRecord = player as JsonRecord;
            const playerName =
              (playerRecord.player as string | undefined) ??
              (playerRecord.username as string | undefined);
            if (!playerName) {
              continue;
            }
            const { prizeTokens, prizeText } = parsePrizes(playerRecord, payoutList);
            resultRows.push({
              tournament_id: tid,
              player: playerName,
              finish: toInt(playerRecord.finish),
              prize_tokens: prizeTokens,
              prize_text: prizeText,
              raw: playerRecord,
              updated_at: nowIso,
            });
          }
        }

        processed += 1;
      }

      if (eventRows.length) {
        await upsertInChunks(supabase, "tournament_events", eventRows, EVENT_BATCH, "tournament_id");
      }
      if (resultRows.length) {
        await upsertInChunks(
          supabase,
          "tournament_results",
          resultRows,
          RESULT_BATCH,
          "tournament_id,player",
        );
      }

      await supabase.from("tournament_ingest_state").upsert(
        {
          organizer: org,
          last_success_at: nowIso,
          last_error: null,
          last_event_count: eventRows.length,
          last_result_count: resultRows.length,
          last_window_days: maxAgeDays,
          updated_at: nowIso,
        },
        { onConflict: "organizer" },
      );

      results.push({
        organizer: org,
        events: eventRows.length,
        results: resultRows.length,
        processed,
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      await supabase.from("tournament_ingest_state").upsert(
        {
          organizer: org,
          last_error: message,
          last_window_days: maxAgeDays,
          updated_at: nowIso,
        },
        { onConflict: "organizer" },
      );
      results.push({ organizer: org, error: message });
    }
  }

  return new Response(JSON.stringify({ ok: true, organizers: results }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
});
