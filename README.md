# Super Supportive Metadata

## Installing
Using poetry, do `poetry install` then run with `poetry run python`.

## File Structure
```
data
├── patreon
│   ├── deadlines.csv
│   ├── events.csv
│   ├── initial.csv
│   └── lock
├── royalroad
│   ├── cache
│   ├── initial.csv
│   └── lock
└── temp
    └── intermediary.csv
```

The `initial.csv` file holds the basic data of each chapter/post, like its ID, when it was published, etc. The `deadlines.csv` holds when the chapter was supposed to be published, as well as any associated metadata (such as if the due date was "approximate," or if this is a modified due date after an update was posted).

`lock` files are currently unimplemented, as there are some issues integrating it into the merging. `cache` is only implemented for royalroad (as patreon email fetches for a local email are decently quick), and holds backups of the royalroad pages of the chapters, to be parsed with any functions later.

The `intermediary.csv` is a merge of many files, which also does some post-processing and adds some more features.

## Config
The config is located in a `yaml` file. Here is an example config:

```
email_settings:
  imap_server: 127.0.0.1
  imap_port: 1143
  email: myemail@example.com
  password: password
royalroad_fetch:
  url: https://www.royalroad.com/fiction/63759/super-supportive
```

Copy over your config to `config.yaml` for the scripts to run correctly.

## Updating
### Convenience
Simply run `scripts/run.sh` for a full update.

### Patreon
Run `scripts/update_patreon.py` to update the patreon data. This pulls from an email provider to parse patreon email notifications (see [config](#Config) on how to set this up, this has been successfully tested with a local email server mirroring remote from protonmail-bridge). Note that the email processing and whatnot is done locally, nothing is sent anywhere. For details, look in the `PatreonEmailFetch` in `chaplib/fetch.py`.

For command line arguments, run `scripts/update_patreon.py --help`

Unfortunately I don't think that the Patreon API supports getting data from other creators, so parsing email is one of the only solutions.
### Royalroad
Run `scripts/update_royalroad.py` to update the royalroad data. This fetches directly from royalroad. As fetching some 300 urls can take a while, and be bad on royalroad's servers, after an initial fetch, urls are stored in a cache. To repopulate the cache, provide `--cache-refresh` to the script. See all arguments with `scripts/update_royalroad.py --help`.
### Intermediary
Combine and update the intermediary data with `scripts/intermediary.py`.


## Plotting
Plot with `scripts/plot_patreon.py` and `scripts/plot_royalroad_wc.py`. By default, this saves plots to files, if you want an interactive window, use the `-p` parameter. See other plot configurations with `--help`. Update and plot at the same time by running `scripts/run.sh -p`.

