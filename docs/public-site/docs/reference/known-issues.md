# Known Issues

This page tracks known issues, limitations, and their workarounds in the current ADEPT release.

## Current Known Issues

### Testing

- **CLI config/background tests**: Some tests fail attempting to create directories in restricted paths. Core functionality still validates correctly (60-80% pass rate).
    - **Workaround**: These failures do not indicate broken features.

- **CLI navigation tests**: 5 of 28 tests fail due to stdin reading without the `-s` flag.
    - **Workaround**: Pass `-s` flag for interactive feature tests. 82% pass rate without it.

- **SSL redirect assertion**: 1 NGINX proxy test fails on SSL redirect assertion.
    - **Workaround**: Manual verification confirms SSL redirects function correctly in practice.

- **Presigned URL unit tests**: 10 of 17 tests fail because mocks cover the HTTP layer but not the Redis file-lookup path.
    - **Workaround**: Integration tests validate the full presigned URL flow end-to-end.

### Port Mapping

- **Agent Gateway port**: The Agent Gateway maps container port 8081 to **host port 8083**. Generated URLs and documentation may incorrectly reference `localhost:8081`.
    - **Workaround**: Always use `localhost:8083` when accessing the Agent Gateway from the host.

### Credential Management

- **Docker restart does not reload .env**: Running `docker restart <service>` does not pick up changes to environment files.
    - **Workaround**: Use `make rebuild-<service>` or `docker compose up -d <service>` instead.

### Unit Test Coverage

- **Stub test files**: 162 of 173 unit test files are stubs awaiting implementation (7.75% module coverage).
    - **Workaround**: E2E test suite provides comprehensive coverage for critical paths.

## Workarounds

For general troubleshooting steps, see the [Troubleshooting Guide](troubleshooting.md).

!!! tip "Validation Commands"
    Run `make validate-service-health` for a comprehensive system check that reports all failing components with suggested fixes.

## Reporting New Issues

When reporting issues:

1. Include the output of `docker ps` and `make validate-service-health`
2. Attach relevant service logs (`docker logs <service> --tail 100`)
3. Note your branch and most recent commit hash
4. Describe expected vs actual behavior
5. File issues on the project's GitHub repository with the appropriate label
