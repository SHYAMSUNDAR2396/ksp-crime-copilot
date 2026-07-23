# Catalyst authentication and identity boundary

The request flow follows the root `PLAN.md` architecture: Catalyst
authentication happens at the edge, then the function resolves the
authenticated principal to an existing `Employee` row before rank-derived
RBAC runs. A browser-supplied `employee_id` is never trusted.

## Required deployment configuration

1. Configure the Advanced I/O Security Rules from
   [`catalyst-security-rules.json`](catalyst-security-rules.json), or apply
   equivalent API Gateway authentication and throttling rules.
2. Provision each Catalyst user and set `KSP_AUTH_EMPLOYEE_MAP` as a JSON
   object mapping an authenticated Catalyst `user_id`, `zuid`, or `email_id`
   to the corresponding `Employee.EmployeeID`.
3. Deploy and verify one mapped user per rank bucket. An absent or invalid
   mapping fails closed with `CAPABILITY_DENIED`; it cannot select a caller.

The mapping is deployment configuration, not case data and not a client-side
secret. Do not put it in the browser or commit production identities.

## Smoke checks

- Unauthenticated calls are rejected by the gateway.
- An authenticated user with no mapping is rejected by the function.
- A mapped user is looked up again through `Employee -> Rank` and receives
  only the rank/unit/district scope derived by the server.
- A forged request body containing another `employee_id` still authorizes as
  the authenticated principal.
- The same identity boundary is used by `crime_query` and `silent_match`.
