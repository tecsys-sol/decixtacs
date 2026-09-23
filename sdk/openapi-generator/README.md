# Generated clients (openapi-generator)

For teams that prefer fully generated code covering **every** endpoint, `make sdk` regenerates
Python and Go clients from `docs/api/openapi.json` with the official
[`openapitools/openapi-generator-cli`](https://openapi-generator.tech) Docker image:

```bash
make openapi   # refresh docs/api/openapi.json from the backend code (needs the backend venv)
make sdk       # -> sdk/generated/python, sdk/generated/go   (needs Docker)
```

| File | Purpose |
|---|---|
| `python.yaml` | generator options for `-g python` (package `networkops_generated`, urllib3 library, pydantic v2 models) |
| `go.yaml` | generator options for `-g go` (package `networkopsgen`) |
| `.openapi-generator-ignore` | copied into each output dir; suppresses CI/git helper files |

The generator version is pinned in the root `Makefile` (`OPENAPI_GENERATOR_IMAGE`). Output goes
to `sdk/generated/` (git-ignored); tagged releases attach both clients as tarballs.

Notes

* Operation ids are FastAPI's defaults (e.g. `list_devices_api_v1_devices_get`), so generated
  method names are verbose. The hand-written clients (`sdk/python`, `sdk/go`) have idiomatic
  names, automatic token refresh and pagination helpers - prefer them unless you need an
  endpoint they do not wrap (both also expose a raw request method).
* Authentication: the spec declares HTTP bearer auth. Pass an API token (`nomt_...`) as the
  bearer token, or implement the `/auth/login` + `/auth/refresh` flow yourself.
* Agent endpoints (`/tacacs/agent/*`, `/accounting/ingest`, `POST /sessions`) take the TACACS
  agent token, not a user token.
