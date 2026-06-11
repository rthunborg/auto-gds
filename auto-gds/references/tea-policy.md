# Legacy Testing Policy

Auto-GDS V0 does not run the old BMM Test Architect workflow by default.

Do not call the old BMM Test Architect commands from the core Auto-GDS path. The runtime config ships with
`testing.enabled: false`, and the production pipeline only delegates GDS/BMGD story creation,
development, code review, project context generation, and retrospective work.

Future GDS testing integration may map to dedicated BMGD skills such as:

- `gds-test-design`
- `gds-test-automate`
- `gds-test-review`
- `gds-performance-test`
- `gds-playtest-plan`
- `gds-test-framework`
- `gds-e2e-scaffold`

Until that mapping exists, treat testing integration as disabled/future work.
