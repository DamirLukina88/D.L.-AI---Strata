# api-latency

`bench.py` reports request latency from the production access log.

The data is not in this repository: export it on the API server with `export_log.sh --since 7d > data/requests.csv`
and copy the file here before running `python3 bench.py`.
