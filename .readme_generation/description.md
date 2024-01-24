<!-- Please provide a short overview of the features of this service. -->

This repository contains two services for the management, authentication and authorization of users of the GHGA data portal.

These two services are described in the following sections. The setting `run_auth_adapter` can be used to determine which of the two services will be started.

### Auth Adapter

The `auth_adapter` sub-package contains the authentication service used by the API gateway via the ExtAuth protocol.

If a `path_prefix` has been configured for the AuthService in the API gateway, then the `api_root_path` must be set accordingly.

### User Management

The `user_management` sub-package contains the user data management service.

The user management contains two APIs, the `users` API for the user registry, and the `claims` API for the claims repository. The setting `include_apis` can be used to specify which of the two APIs should be provided. For testing purposes, both APIs can be provided at the same time, but this is not recommended in production.
