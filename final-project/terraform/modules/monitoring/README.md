# Module `monitoring`

One job: the secret `grafana-admin` in the namespace `monitoring`, with the
keys `admin-user` and `admin-password`. The password is a `random_password`,
and the Grafana chart reads the secret with `admin.existingSecret`, so it never
appears in Git.

Prometheus, Grafana, Loki, Alloy, PushGateway and OpenCost are Helm charts
deployed by Argo CD, not by Terraform. Nothing was invented here to make the
module look bigger.

Read the password with:

```bash
kubectl -n monitoring get secret grafana-admin -o jsonpath='{.data.admin-password}' | base64 -d
```
