# NAMOA

NAMOA is a media intelligence and optimisation application. It scans a
media library, analyses files with FFprobe, stores the results in SQLite,
and presents recommendations through a web interface. Approved optimisations
run through FFmpeg with verification, backup, and rollback boundaries.

This repository is the public runtime distribution. It contains the
application source, runtime configuration, Docker packaging, the Ubuntu
installer, and the TrueNAS SCALE app template. It intentionally excludes the
private AI control plane, internal documentation, test scripts, development
history, working databases, and logs.

## Requirements

The recommended installation uses Docker. The host does not need Python,
FFmpeg, pip, npm, or Node.js installed.

- Docker Engine
- Docker Compose plugin
- A media library path that the container can read and, for approved
  optimisation or organisation execution, write to

FFmpeg and FFprobe are installed inside the image. The current image is
built for CPU encoding with `libx265`. No GPU is required.

## Public container image

The published image is:

```text
ghcr.io/righteous84/namoa:latest
```

Versioned releases are also published, for example:

```text
ghcr.io/righteous84/namoa:0.1.0
```

The GitHub Container Registry package must have public visibility. If a pull
returns `denied`, the package is still private. The repository owner can change
that under the package settings in GitHub.

## Quick start on Ubuntu

```bash
git clone https://github.com/righteous84/NAMOA-public.git
cd NAMOA-public
cp .env.example .env
```

Edit `.env` and set at least:

```dotenv
NAMOA_MEDIA_ROOT=/path/to/your/media
PUID=1000
PGID=1000
```

Use the UID and GID that own the media library and the NAMOA data
directories:

```bash
id -u
id -g
```

Then start NAMOA:

```bash
./install.sh
```

If Docker is not installed, use:

```bash
./install.sh --install-docker
```

If the published image is available and you do not want to build locally:

```bash
./install.sh --image
```

If the image pull returns `denied`, the GHCR package is still private. Either
make the package public or use `./install.sh` to build the image locally from
this repository.

Open:

```text
http://localhost:8080
```

## First run

1. Open the NAMOA web interface.
2. Go to Scan.
3. Enter the media path as it exists inside the container.
4. Run the scan.
5. Review recommendations before approving anything.

Nothing is modified during scan or analysis. Approved execution replaces the
working file in place through the verified execution lifecycle, with a
recorded backup for rollback.

## Media paths

The compose file mounts the host media path at the same path inside the
container:

```text
${NAMOA_MEDIA_ROOT}:${NAMOA_MEDIA_ROOT}
```

This is deliberate. NAMOA stores file paths in its database. If the database
records `/mnt/media_drv1/Movies`, the container must see the library at
`/mnt/media_drv1/Movies`, not at a different path such as `/media`.

For a new installation, choose one stable container path and use it
consistently. For an existing database, mount the library at the paths already
recorded there.

If you have more than one library root, add another volume entry in
`compose.yaml` or in the TrueNAS app YAML:

```yaml
      - /mnt/other-library:/mnt/other-library
```

The container needs write access to a media directory only when you approve
an operation that replaces or moves a file there.

## Configuration

The installer copies `.env.example` to `.env` on first use and sets `PUID` and
`PGID` to the current user.

| Variable | Default | Purpose |
|---|---|---|
| `NAMOA_PORT` | `8080` | Host port for the web interface |
| `NAMOA_VERSION` | `latest` | Container image tag |
| `NAMOA_MEDIA_ROOT` | `/mnt/media` | Host media path, mounted at the same path inside the container |
| `NAMOA_DATA_DIR` | `./data` | Persistent SQLite database and Preview artifacts |
| `NAMOA_CONFIG_DIR` | `./config-data` | Persistent secret store and local settings |
| `NAMOA_LOG_DIR` | `./logs` | Persistent application logs |
| `PUID` | `1000` | UID the container runs as |
| `PGID` | `1000` | GID the container runs as |

The application image contains the runtime JSON configuration under
`/app/config`. The mounted `config-data` directory is for operator state, not
for replacing the packaged defaults.

## TrueNAS SCALE

TrueNAS CORE is FreeBSD and cannot run this Linux Docker image directly. Use
TrueNAS SCALE or Community Edition.

1. Create datasets for persistent state, for example:

```text
/mnt/tank/apps/namoa/data
/mnt/tank/apps/namoa/config
/mnt/tank/apps/namoa/logs
```

2. Make sure the media dataset exists and is accessible to the UID and GID
   that the container will use.

3. In TrueNAS SCALE, open Apps, choose Discover, then Custom App, then
   Install via YAML.

4. Paste and adapt `truenas/app.yaml`. Replace every `/mnt/tank/...` path and
   set `user` to the UID:GID that owns the datasets.

5. Install and wait for the container health check to pass.

6. Open:

```text
http://<truenas-ip>:8080
```

The TrueNAS template uses the published image:

```text
ghcr.io/righteous84/namoa:latest
```

Pin a version tag instead of `latest` for reproducible installations:

```yaml
    image: ghcr.io/righteous84/namoa:0.1.0
```

If the image pull returns `denied`, the GHCR package is still private. Make the
package public in GitHub, then retry the app installation.

The `user:` value in the YAML must match the owner of the data, config, logs,
and media datasets. `1000:1000` is only an example. On TrueNAS, use the UID and
GID shown in the dataset permissions or the Apps user configuration.

To upgrade a TrueNAS installation, back up the datasets, change the image tag
in the app YAML or app settings, and apply the update. Database migrations run
automatically on startup.

## Building the image yourself

```bash
docker build -t ghcr.io/righteous84/namoa:local .
```

The image runs:

```bash
python3 -m app.main serve 0.0.0.0 8080 --db /data/media.db
```

Migrations run automatically at startup. The image does not contain a
database. A fresh `/data` volume produces a fresh database.

## Upgrades

Back up the data directory before upgrading.

```bash
docker compose build --pull
docker compose up -d
```

Or, when using the published image:

```bash
docker compose pull
docker compose up -d --no-build
```

Database migrations run automatically. The existing `/data/media.db` is
preserved.

## Backup

The persistent state is:

```text
data/media.db
data/previews/
config-data/
logs/
```

Stop the container before copying the database, or use a filesystem snapshot:

```bash
docker compose stop
cp -a data "data-backup-$(date +%Y%m%d-%H%M%S)"
docker compose start
```

On TrueNAS, datasets and snapshots are the preferred backup mechanism.

## Security

- NAMOA has no built-in authentication.
- Keep it on a trusted local network.
- Do not expose port 8080 directly to the internet.
- If remote access is required, place NAMOA behind an authenticated reverse
  proxy and use TLS.
- The container can read and write mounted media when you grant write
  permission.
- Run the container as the UID and GID that own the data and media paths.
- Do not mount the host home directory or the source checkout into the
  container.

## Troubleshooting

### Docker permission denied

Add your user to the Docker group and log in again:

```bash
sudo usermod -aG docker "$USER"
```

### Port already in use

Change `NAMOA_PORT` in `.env`.

### Media path does not exist

Set `NAMOA_MEDIA_ROOT` in `.env` to an existing host path. The installer
checks this before starting.

### Permission denied writing media

Set `PUID` and `PGID` in `.env` to the owner of the media library, or adjust
the dataset or filesystem permissions.

### FFmpeg or FFprobe missing

The published image installs both. If you built a custom image, confirm that
the `ffmpeg` package is installed and that both `ffmpeg` and `ffprobe` are on
`PATH`.

### Logs

```bash
docker compose logs -f namoa
```

or inspect `logs/namoa.log` inside the mounted log directory.

## Publishing a release

Maintainers publish a version by tagging the public repository:

```bash
git tag v0.1.0
git push origin v0.1.0
```

The GitHub Actions workflow builds and publishes the matching image:

```text
ghcr.io/righteous84/namoa:0.1.0
```

After the first package publish, set the GitHub Container Registry package
visibility to public. Anonymous users and TrueNAS SCALE must be able to pull it.

Use the version tag in production:

```dotenv
NAMOA_VERSION=0.1.0
```

or directly in the TrueNAS YAML:

```yaml
    image: ghcr.io/righteous84/namoa:0.1.0
```

## Licence

See `LICENSE`.
