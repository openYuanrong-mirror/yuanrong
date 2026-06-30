curl -X POST "http://172.17.0.2:8888/api/jobs"   -H "Content-Type: application/json" -d '{
    "entrypoint": "python -m yr.cli.scripts sandbox create --name 123456789 --namespace sandbox",
    "runtime_env": {
      "working_dir": "/tmp"
    }
  }'
