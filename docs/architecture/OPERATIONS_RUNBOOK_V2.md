# Operations runbook V2

Use the rollout SSH config:

```powershell
ssh -F C:\Users\Lenovo\Documents\customization_windows\ssh-config-s7-s13.conf s13 'hostname; whoami; pwd'
ssh -F C:\Users\Lenovo\Documents\customization_windows\ssh-config-s7-s13.conf s7 'hostname; whoami; pwd'
```

Expected identities are `sergey` on S13 and `wanga` on S7. On S13, the
verified S7 data route is `ssh -i /home/sergey/.ssh/id_to_nyx wanga@s7`.
Do not substitute historical 10.8.x addresses or start the completed composite
service. Dataset work must remain development-only and must not launch model
training or OOS evaluation.
