import argparse
from dashboard.server import Dashboard

parser = argparse.ArgumentParser(description="Script Manager local Dashboard")
parser.add_argument("--root", default=".")
parser.add_argument("--port", type=int, default=8765)
args = parser.parse_args()
server = Dashboard(args.root, args.port)
print("Script Manager: http://127.0.0.1:" + str(server.server_address[1]), flush=True)
try:
    server.serve_forever()
except KeyboardInterrupt:
    pass
finally:
    server.server_close()
