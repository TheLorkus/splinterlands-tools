create table if not exists public.point_schemes (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique,
  label text not null,
  mode text not null default 'fixed',
  base_points numeric default 0,
  dnp_points numeric default 0,
  rules jsonb not null,
  created_at timestamptz default now(),
  updated_at timestamptz default now(),
  constraint point_schemes_mode_check check (mode in ('fixed', 'multiplier'))
);

create index if not exists point_schemes_slug_idx on public.point_schemes (slug);

alter table public.point_schemes enable row level security;

drop policy if exists point_schemes_select_public on public.point_schemes;
create policy point_schemes_select_public
  on public.point_schemes
  for select
  using (true);

drop policy if exists point_schemes_write_service_role on public.point_schemes;
create policy point_schemes_write_service_role
  on public.point_schemes
  for all
  to authenticated, service_role
  using (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');

-- Seed default scoring schemes (idempotent via slug conflict).
insert into public.point_schemes (slug, label, mode, base_points, dnp_points, rules)
values (
  'balanced',
  'Balanced',
  'fixed',
  0,
  0,
  jsonb_build_array(
    jsonb_build_object('min', 1, 'max', 1, 'points', 25),
    jsonb_build_object('min', 2, 'max', 2, 'points', 18),
    jsonb_build_object('min', 3, 'max', 4, 'points', 12),
    jsonb_build_object('min', 5, 'max', 8, 'points', 8),
    jsonb_build_object('min', 9, 'max', 16, 'points', 5),
    jsonb_build_object('min', 17, 'max', null, 'points', 2)
  )
)
on conflict (slug) do update
set label = excluded.label,
    mode = excluded.mode,
    base_points = excluded.base_points,
    dnp_points = excluded.dnp_points,
    rules = excluded.rules,
    updated_at = now();

insert into public.point_schemes (slug, label, mode, base_points, dnp_points, rules)
values (
  'performance',
  'Performance-Focused',
  'fixed',
  0,
  0,
  jsonb_build_array(
    jsonb_build_object('min', 1, 'max', 1, 'points', 50),
    jsonb_build_object('min', 2, 'max', 2, 'points', 30),
    jsonb_build_object('min', 3, 'max', 3, 'points', 20),
    jsonb_build_object('min', 4, 'max', 4, 'points', 15),
    jsonb_build_object('min', 5, 'max', 8, 'points', 10),
    jsonb_build_object('min', 9, 'max', 16, 'points', 5),
    jsonb_build_object('min', 17, 'max', null, 'points', 1)
  )
)
on conflict (slug) do update
set label = excluded.label,
    mode = excluded.mode,
    base_points = excluded.base_points,
    dnp_points = excluded.dnp_points,
    rules = excluded.rules,
    updated_at = now();

insert into public.point_schemes (slug, label, mode, base_points, dnp_points, rules)
values (
  'participation',
  'Participation',
  'multiplier',
  1,
  0,
  jsonb_build_array(
    jsonb_build_object('min', 1, 'max', 1, 'multiplier', 3.0),
    jsonb_build_object('min', 2, 'max', 2, 'multiplier', 2.5),
    jsonb_build_object('min', 3, 'max', 4, 'multiplier', 2.0),
    jsonb_build_object('min', 5, 'max', 8, 'multiplier', 1.5),
    jsonb_build_object('min', 9, 'max', 16, 'multiplier', 1.2),
    jsonb_build_object('min', 17, 'max', null, 'multiplier', 1.0)
  )
)
on conflict (slug) do update
set label = excluded.label,
    mode = excluded.mode,
    base_points = excluded.base_points,
    dnp_points = excluded.dnp_points,
    rules = excluded.rules,
    updated_at = now();
