### Kubernetes (Weather Skills Helm chart)

See [charts/weather-skills-chat/README.md](charts/weather-skills-chat/README.md).

```bash
helm install weather-skills-chat ./charts/weather-skills-chat \
  --set secretName=weather-skills-chat-secrets
```

Create the Kubernetes Secret externally before installing (see the chart README).
