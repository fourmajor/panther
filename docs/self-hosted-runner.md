# Panther self-hosted runner

## Kiwi production runner

Kiwi runs a persistent, repository-scoped runner in a restricted Docker
container. It provides CI compute after host restarts without Dandelion. The
Panther workflow still accepts only owner-dispatched jobs on reviewed `main`
or `codex/` branches. The container has two CPUs, 4 GiB RAM, no host mounts,
no Docker socket, no AWS credentials, and no private game files. Its registration
credential remains inside the container; a new registration is required if
that container is removed.

Install from reviewed Panther source on Kiwi. Obtain a short-lived runner
registration token using the owner's GitHub CLI on a trusted computer and pipe
it directly over SSH to the Kiwi installer. The installer builds the pinned
runner image before registration, and the token is not written to the host:

```sh
gh api --method POST repos/fourmajor/panther/actions/runners/registration-token --jq .token \
  | ssh stu@kiwi 'cd /srv/panther/ci-runner/repo && bash ops/runner/start-kiwi.sh'
```

The Kiwi checkout must be updated to the reviewed commit before running this
command. Once registered, jobs can be dispatched through GitHub without
Dandelion running. Verify `panther-kiwi-ci` is online in GitHub and dispatch a
representative `ci.yml` run. Container logs and status are available with
`docker logs panther-kiwi-ci` and `docker inspect panther-kiwi-ci`. Docker's
`unless-stopped` policy starts the container after a normal Docker restart;
an actual host reboot still requires Stu's separate authorization.

To update the runner image, first confirm no job is active, then stop and
remove only `panther-kiwi-ci`, delete its exact GitHub runner registration,
update the reviewed checkout, and register a new container. Do not prune other
Docker resources. If Kiwi is unavailable, the old Dandelion script below is a
manual recovery path, not an automatic second worker.

## Former Dandelion one-job runner

Before the Kiwi move, Panther's manually dispatched CI ran in a Linux Docker
container on the owner's MacBook. This path remains available for manual
recovery. It requires the laptop to be awake with Docker Desktop running.

## Start and run

Prerequisites: Docker, GitHub CLI authenticated as the repository owner with runner administration
permission, and a reviewed checkout. Start Docker Desktop with `docker desktop start` if needed.

```sh
bash ops/runner/start.sh
gh workflow run ci.yml --repo fourmajor/panther --ref main
gh run list --repo fourmajor/panther --workflow ci.yml --limit 1
```

Frontend-affecting changes must pass Playwright **on this self-hosted runner before merge**.
Review and push the PR branch, then replace `main` above with its `codex/...` branch name.
The workflow installs Chromium and runs the named `Playwright browser tests (self-hosted)` step.
Wait for success on the latest PR commit and record the run URL in the PR. Direct host-browser
tests or GitHub-hosted runs do not substitute for this gate. Never dispatch untrusted fork code.

The start script builds a pinned, checksum-verified GitHub runner image, registers a new repository
runner using a short-lived token passed over stdin, and starts it. The token is not saved in the
image, environment, repository, or host file. Runner credentials live only inside that container.
Each runner accepts **one job**, then unregisters and exits. Start a fresh one before the next job.
There is no daemon on the Mac automatically renewing registrations or launching more containers.

The script prints the exact container name and commands to view its logs and remove it after the
job. Containers are retained on exit so failed-job diagnostics remain available. Remove completed
containers promptly: their workspaces and runner logs are not intended as long-term storage.
Do not use broad Docker prune commands; other containers may belong to unrelated projects.

To stop an idle runner early, stop its exact container with `docker --context desktop-linux stop
<name>`, find its ID with `gh api repos/fourmajor/panther/actions/runners`, and delete that runner
registration with `gh api --method DELETE repos/fourmajor/panther/actions/runners/<id>`. Then remove
the exact stopped container. Completed ephemeral runners normally remove their own registration.

## Security and limits

- Manual dispatch only, on reviewed `main` or `codex/` branches in `fourmajor/panther`, by
  `fourmajor` (including reruns). No PR or fork event triggers.
- Read-only workflow token; checkout does not retain Git credentials.
- Non-root container, dropped capabilities, no privilege escalation, two CPUs and 4 GiB RAM.
- No host directories, Docker socket, AWS keys, SSH agent, or personal files mounted.
- No deployment permissions. CDK synthesis is tested offline; deployment stays on the laptop.
- Outbound networking is required. Docker is **not** a complete sandbox for hostile code or a
  network firewall. GitHub warns against running untrusted public-repository code on self-hosted
  runners. Keep dispatch restricted, review dependencies/workflows, and never approve arbitrary
  contributor jobs on this machine.
- Container jobs and Docker build steps are intentionally unsupported without a Docker socket.
- Runner application auto-updates within its disposable container. Keep the pinned runner release
  and checksum in the Dockerfile current; rebuild to refresh OS packages as well.

## Move to another computer

Install Docker and GitHub CLI, clone Panther, and run the same start script. ARM64 and x86-64 Linux
containers are supported. On a Linux Docker host set `PANTHER_DOCKER_CONTEXT=default`; the Mac
defaults explicitly to `desktop-linux` to avoid accidentally using a remote Docker engine.
Stop and unregister any idle MacBook runner when moving. Workflows use `panther-local`, not a
machine name, so they do not need changing. No home-host infrastructure belongs in AWS CDK.

Reference: [GitHub self-hosted runners](https://docs.github.com/en/actions/reference/runners/self-hosted-runners).
