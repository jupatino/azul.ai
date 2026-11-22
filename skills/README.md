# Persistent Azul agent skills

This directory is bind-mounted into the Azul agent container at `/app/skills`.
Files created here through Slack remain on the host when the container is
recreated.

The agent's file tools are restricted to this directory.
