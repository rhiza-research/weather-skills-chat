# The realm file is copied into the image instead of bind-mounted. A bind mount's source path is
# resolved on the Docker daemon's host. When the daemon runs on a different machine from this
# checkout, Docker creates an empty directory at that path, Keycloak's directory import finds no
# .json files, reports success, and serves no realm. A build context is sent to the daemon, so the
# file is always present.
FROM quay.io/keycloak/keycloak:26.7.3

# After editing the realm file, rebuild the image and recreate the container. --import-realm skips
# the import when the realm already exists, so a restart does not apply the change. Recreating the
# container also deletes the dev database and every user in it. Run from the repository root:
#
#   docker compose -f docker-compose.yaml -f docker-compose.keycloak.yaml up -d --build --force-recreate keycloak
COPY realm-weather-skills-chat.json /opt/keycloak/data/import/realm.json
