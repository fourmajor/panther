"""Deployment-supplied capabilities; no account identities or permissive defaults in source."""

import os


def authorized(claims, capability):
    names = {name for name in os.environ.get(capability, "").split(",") if name}
    username = claims.get("cognito:username", claims.get("username"))
    return bool(claims.get("sub")) and isinstance(username, str) and username in names
