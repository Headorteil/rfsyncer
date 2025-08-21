# Rfsyncer

Rfsyncer is a simple tool which takes as input a directory containing a file tree.

This tree can be compared and uploaded to one ore more remote hosts.

A simple tree would be :

```
$ tree
.
└── root
    ├── etc
    │   ├── hosts
    │   ├── hosts.rfsyncer
    │   ├── passwd
    │   └── zsh
    │       └── zprofile
    ├── root.rfsyncer
    └── root
        └── .ssh
            └── authorized_keys
```

By using `rfsyncer diff --hosts user@1.2.3.4 --hosts MyHost --root ./root`, rfsyncer will connect to both hosts (it is able to automatically parse some fields of the ssh config file) and compare the remote files and local files. By remplacing `diff` by `install` in the command line, it will resolve diffs by uploading local files to hosts.

Rfsyncer offers the possibility to use jinja2 as a templating engine if needed.

Pre-hooks are availible to offer more templating possibilities.

> [!CAUTION]
> Pre-hooks are run even with the diff command. They should not modify the system.
>
> Post-hooks are run only with the install command.

# Installation

- `uv tool install rfsyncer`
- `pipx install rfsyncer`
- `pip install rfsyncer`

# Configuration

With rfsyncer, everything is templatized.

## Config file

Config file is specified with the `--config`.

- `env` is populated with env vars (`./.env` file is automatically loaded)
- `flag` is populated with the content of `--flag`

That gives us this kind of config file :
```yaml
general:
  key1: value1 # Arbitrary keys to template files for all hosts
  pre_hooks:
    - name: test
      path: ./hooks/test.sh

hosts:
  host1:
    sudo: true # Use sudo to install files as root and be able to read them when in diff mode (default : false)
    password: {{ env.HOST1_PASSWORD }} # Needed to use sudo
    pre_hooks:
      - name: test-host1
        path: ./hooks/test-host1.sh
  host2:
    enabled: {{ flag.host2.enabled }} # Enable or disable host
    hostname: 1.2.3.4 # IP or domain of the remote host
    user: user # User of the ssh host
    port: 2222 # SSh port (default : 22)
    identityfile: # Path to ssh key
    host_key1: false # Arbitrary keys to template files for this host
    host_key2: value2
  host3: {} # Can works with nothing more than host thanks to the ssh config
```

## .rfsyncer files

To customize the default behaviour on a specific file, you can create a `<file_name>.rfsyncer` in the same dir as it.

For example, if you want to customize `root/etc/hosts`, create `root/etc/hosts.rfsyncer`

- `general` is populated with the general section of the config
- `general.flag` is populated with the content of `--flag`
- `general.env` is populated with env vars (`./.env` file is automatically loaded)
- `host` is populated with the corresponding host section of the config with some additions :
  - `real_hostname` is the output of `$ hostname`
- `hook` is populated with the results of pre-hooks

That gives us this kind of .rfsyncer file :
```yaml
{% if host.real_hostname == "IAmHost1" %}
enabled: false # Determines if the file should be taken into account (default : true)
{% endif %}
{% if general.key2 %}
templating: j2 # Enable jinja templating for the related file (default : no templating)
{% endif %}
name: dir-{{ host.host_key2 }} # If provided, will replace the original name of the file. It can even be a path.
```

> The name field can be very powerfull, especially for directories as it will impact all their childs which will follow the new path of their parent.

## Normal files

When templating is enabled for a file, jinja2 templating is applied to it.

- `general` is populated with the general section of the config
- `general.flag` is populated with the content of `--flag`
- `general.env` is populated with env vars (`./.env` file is automatically loaded)
- `host` is populated with the corresponding host section of the config with some additions :
  - `real_hostname` is the output of `$ hostname`
- `hook` is populated with the results of pre-hooks

For example :

```jinja2
Hello {{ general.env.ENV_VAR }}
{{ general.flag.flag1 | default("default") }}
{{ general.key1 }}
{{ host.real_hostname }}
{% if general.key1 %}Yipee{% endif %}
The hook stderr was {{ hook.test.stderr }}
```

## Hooks files

### Pre hooks

They are bash scripts which are run on the remote hosts before the diff or the install.

General hooks are run before hosts specific hooks.

The hook adds fields to `.rfsyncer` and normal files with `hook.<hook name>.stdout` and `hook.<hook name>.stderr`

The pre hooks are templatized withe the following values :

- `general` is populated with the general section of the config
- `general.flag` is populated with the content of `--flag`
- `general.env` is populated with env vars (`./.env` file is automatically loaded)
- `host` is populated with the corresponding host section of the config with some additions :
  - `real_hostname` is the output of `$ hostname`

For example :

```jinja2
{% if host.real_hostname == "zozo" %}
uname -m
{% endif %}
```

### Post hooks

They are bash scripts which are run on the remote hosts after the diff and the install.

General hooks are run before hosts specific hooks.

The post hooks are templatized withe the following values :

- `general` is populated with the general section of the config
- `general.flag` is populated with the content of `--flag`
- `general.env` is populated with env vars (`./.env` file is automatically loaded)
- `host` is populated with the corresponding host section of the config with some additions :
  - `real_hostname` is the output of `$ hostname`
- `hook` is populated with the results of pre-hooks
- `paths` is populated with the results of the diff

`paths` variable has the following form :
```json
{
  "<local path relative to the root flag>":
    {
      "state": "<create|update|keep|error>",
      "remote_path": "<absolute remote path>"
    }
}
```

An example of a post hook would be :

```jinja2
{% if paths["etc/hosts"].state == "update" %}
reboot
{% else %}
echo Nothing to do on {{ host.real_hostname }}
{% endif %}
```

# Usage

```
$ rfsyncer -h

 Usage: rfsyncer [OPTIONS] COMMAND [ARGS]...

 Rfsyncer by Headorteil 😎


╭─ Options ───────────────────────────────────────────────────────────────────────────────────────────╮
│ --config              -c      PATH     Config path (or - for stdin) [default: config.yml]           │
│ --dotenv              -e      PATH     Dotenv path [default: .env]                                  │
│ --processes           -p      INTEGER  Number of processes to pop [default: 4]                      │
│ --flag                -f      TEXT     json to pass to templating engines                           │
│ --version             -V               Print the tool version                                       │
│ --install-completion                   Install completion for the current shell.                    │
│ --show-completion                      Show completion for the current shell, to copy it or         │
│                                        customize the installation.                                  │
│ --help                -h               Show this message and exit.                                  │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Display ───────────────────────────────────────────────────────────────────────────────────────────╮
│ --verbosity-level  -v                        INTEGER RANGE [0<=x<=3]     Change the logs verbosity  │
│                                                                          [default: 2]               │
│ --log-to-file          --no-log-to-file                                  Enable file logging (path  │
│                                                                          defined in config)         │
│                                                                          [default: log-to-file]     │
│ --display              --no-display      -D                              Display things that are    │
│                                                                          not logs nor live like     │
│                                                                          tables or diffs            │
│                                                                          [default: display]         │
│ --pager            -P  --no-pager                                        Display tables in less     │
│                                                                          [default: no-pager]        │
│ --live             -l  --no-live         -L                              Display live objects like  │
│                                                                          progress bars              │
│                                                                          [default: live]            │
│ --debug            -d  --no-debug                                        Use max verbosity and      │
│                                                                          print file infos with logs │
│                                                                          [default: no-debug]        │
│ --color                                      [standard|truecolor|auto|n  Color system               │
│                                              one|256]                    [default: auto]            │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ──────────────────────────────────────────────────────────────────────────────────────────╮
│ ping      Test connectivity to remote hosts                                                         │
│ install   Install local tree to remote hosts                                                        │
│ diff      Diff local tree with remote trees                                                         │
│ clear     Clear remote hosts of rfsyncer temporary files                                            │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## Diff

> The diff command don't make any change to the destination file system except it will write temporary files to `/tmp/rfsyncer` and `/tmp/rfsyncer_askpass.sh` is sudo is specified.

```
$ rfsyncer diff -h

 Usage: rfsyncer diff [OPTIONS]

 Diff local tree with remote trees


╭─ Options ───────────────────────────────────────────────────────────────────────────────────────────╮
│ --root          -r                         PATH  Root path on wich make diff [default: root]        │
│ --hosts                                    TEXT  Hosts                                              │
│                                                  [default: (all hosts defined in the config file)]  │
│ --sudo          -s  --no-sudo          -S        Exec commands with sudo [default: no-sudo]         │
│ --insecure      -i  --no-insecure      -I        Insecure mode : don't check host keys              │
│                                                  [default: no-insecure]                             │
│ --keep          -k  --no-keep          -K        Keep remote tmp dir [default: no-keep]             │
│ --force-upload  -f  --no-force-upload  -F        Force upload to remote, may be useful with --keep  │
│                                                  [default: no-force-upload]                         │
│ --help          -h                               Show this message and exit.                        │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## Install

```
$ rfsyncer install -h

 Usage: rfsyncer install [OPTIONS]

 Install local tree to remote hosts


╭─ Options ───────────────────────────────────────────────────────────────────────────────────────────╮
│ --root      -r                     PATH  Root path on wich make diff [default: root]                │
│ --hosts                            TEXT  Hosts [default: (all hosts defined in the config file)]    │
│ --sudo      -s  --no-sudo      -S        Exec commands with sudo [default: no-sudo]                 │
│ --insecure  -i  --no-insecure  -I        Insecure mode : don't check host keys                      │
│                                          [default: no-insecure]                                     │
│ --keep      -k  --no-keep      -K        Keep remote tmp dir [default: no-keep]                     │
│ --help      -h                           Show this message and exit.                                │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## Clear

```
$ rfsyncer clear -h

 Usage: rfsyncer clear [OPTIONS]

 Clear remote hosts of rfsyncer temporary files


╭─ Options ───────────────────────────────────────────────────────────────────────────────────────────╮
│ --hosts                            TEXT  Hosts [default: (all hosts defined in the config file)]    │
│ --insecure  -i  --no-insecure  -I        Insecure mode : don't check host keys                      │
│                                          [default: no-insecure]                                     │
│ --help      -h                           Show this message and exit.                                │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

## Ping

```
$ rfsyncer clear -h

 Usage: rfsyncer ping [OPTIONS]

 Test connectivity to remote hosts


╭─ Options ───────────────────────────────────────────────────────────────────────────────────────────╮
│ --hosts                            TEXT  Hosts [default: (all hosts defined in the config file)]    │
│ --sudo      -s  --no-sudo      -S        Exec commands with sudo [default: no-sudo]                 │
│ --insecure  -i  --no-insecure  -I        Insecure mode : don't check host keys                      │
│                                          [default: no-insecure]                                     │
│ --help      -h                           Show this message and exit.                                │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

# Vault usage

Rfsyncer can easily be combined with tools such as [vals](https://github.com/helmfile/vals)

secrets.yml :
```yaml
HOST_PASSWORD: ref+vault://secret/rfsyncer#MY_SECRET
```

config.yml :
```yaml
hosts:
  host1:
    sudo: True
    password: {{ env.HOST_PASSWORD }}
  host2: {}
```

`vals exec -i -f secrets.yml -- rfsyncer diff`


# Good to know

The only file types which are handled are `normal files`, `directories` and `symbolic links`.

When a file (or directory) already exist on the remote host and its content is the same, it will be skipped even if its mode, owner or group are different.

When a file is created or uploaded, its owner and group will be the ones of the ssh user or root if sudo is specified.

Diffs are skipped for binary files and files heavier than 10Mo.

The remote system is expected to hawe a working ssh server running and supports sftp.

Some binaries are expected to existe on the remote hosts (they are already here on most distributions):
- cat
- diff
- hostname (can back off to `cat /proc/sys/kernel/hostname`)
- install
- md5sum
- mkdir
- readlink
- rm
- sh
- stat
