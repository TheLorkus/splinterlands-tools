import { serve } from "https://deno.land/std@0.205.0/http/server.ts";

type SeasonResponse =
  | { ends?: string; end?: string }
  | { season?: { ends?: string; end?: string } }
  | Record<string, unknown>;

const DEFAULT_ENDPOINT = "https://api.splinterlands.com/season?id=171";
const DEFAULT_SCHEDULE_NAME = "season-sync";
const DEFAULT_TARGET_FUNCTION = "season-sync";
const MINUTE_MS = 60 * 1000;

function parseSeasonEnd(data: SeasonResponse): Date {
  const ends =
    (data as { ends?: string }).ends ??
    (data as { end?: string }).end ??
    (data as { season?: { ends?: string; end?: string } }).season?.ends ??
    (data as { season?: { ends?: string; end?: string } }).season?.end;

  const parsed = ends ? new Date(String(ends)) : null;
  if (!parsed || Number.isNaN(parsed.getTime())) {
    throw new Error("Unable to parse season end from API response.");
  }
  return parsed;
}

function cronFromDate(date: Date): string {
  // Cron order: minute hour day month day-of-week (UTC)
  return `${date.getUTCMinutes()} ${date.getUTCHours()} ${date.getUTCDate()} ${
    date.getUTCMonth() + 1
  } *`;
}

serve(async (req) => {
  if (req.method !== "POST") {
    return new Response("Method not allowed", { status: 405 });
  }

  const supabaseUrl = Deno.env.get("SUPABASE_URL");
  const serviceRoleKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!supabaseUrl || !serviceRoleKey) {
    return new Response(
      JSON.stringify({ error: "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required" }),
      { status: 500, headers: { "Content-Type": "application/json" } },
    );
  }

  const seasonEndpoint = Deno.env.get("SYNC_SEASON_ENDPOINT") ?? DEFAULT_ENDPOINT;
  const scheduleName = Deno.env.get("SYNC_SCHEDULE_NAME") ?? DEFAULT_SCHEDULE_NAME;
  const functionName = Deno.env.get("SYNC_FUNCTION_NAME") ?? DEFAULT_TARGET_FUNCTION;

  try {
    const seasonResp = await fetch(seasonEndpoint, { headers: { accept: "application/json" } });
    if (!seasonResp.ok) {
      throw new Error(`Season endpoint failed: ${seasonResp.status} ${seasonResp.statusText}`);
    }

    const season = (await seasonResp.json()) as SeasonResponse;
    const seasonEnds = parseSeasonEnd(season);
    const scheduledFor = new Date(seasonEnds.getTime() - 10 * MINUTE_MS);
    const cron = cronFromDate(scheduledFor);

    const payload = {
      name: scheduleName,
      cron,
      timezone: "UTC",
      enabled: true,
      target: functionName,
      target_type: "function",
    };

    const schedulerResp = await fetch(`${supabaseUrl}/rest/v1/rpc/supabase_scheduler`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        apikey: serviceRoleKey,
        Authorization: `Bearer ${serviceRoleKey}`,
      },
      body: JSON.stringify(payload),
    });

    if (!schedulerResp.ok) {
      const detail = await schedulerResp.text();
      throw new Error(`Scheduler update failed: ${schedulerResp.status} ${detail}`);
    }

    const responseBody = {
      schedule: scheduleName,
      cron,
      seasonEndsAt: seasonEnds.toISOString(),
      scheduledFor: scheduledFor.toISOString(),
    };

    return new Response(JSON.stringify(responseBody), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  } catch (error) {
    console.error("update-season-schedule error", error);
    const message = error instanceof Error ? error.message : "Unknown error";
    return new Response(JSON.stringify({ error: message }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
});
