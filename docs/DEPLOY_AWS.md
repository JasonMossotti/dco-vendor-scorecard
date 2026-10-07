# Deploying on AWS

The demo is published on GitHub Pages, but the same code runs on AWS three ways, from simplest to production-shaped. Check current AWS pricing and Free Tier terms before launching anything, and stop or delete resources you are not using.

| Option | What runs where | Good for |
|---|---|---|
| A. S3 static site | Python runs in the visitor's browser (same build as GitHub Pages) | Cheapest public hosting; no server to patch |
| B. EC2 server | Streamlit runs on a Linux instance | A private demo, or running against data that should not leave a server |
| C. Production architecture | Scheduled jobs inside the site network, reports to S3, app behind authentication | How this would run for real |

## A. Static site on S3

The GitHub Pages build is a plain static site, so S3 can host it unchanged.

```bash
python scripts/build_site.py --out _site            # same build the Pages workflow publishes
aws s3 mb s3://YOUR-BUCKET-NAME
aws s3 sync _site s3://YOUR-BUCKET-NAME --delete
```

Then either enable **Static website hosting** on the bucket (simple, HTTP only, and requires allowing public reads) or, better, put **CloudFront** in front of a private bucket using Origin Access Control. CloudFront adds HTTPS and keeps the bucket itself private.

## B. Streamlit on an EC2 instance

**1. Launch the instance.**
- AMI: Amazon Linux 2023. Instance type: `t3.small` (a `t3.micro` works for light use).
- Security group inbound rules: SSH (22) from **My IP**, and TCP 8501 from **My IP**. Do not open 8501 to the world without authentication in front of it (see option C).

**2. Install and run.** Connect with SSH (or EC2 Instance Connect), then:

```bash
sudo dnf install -y git python3.12        # if not found, update first: sudo dnf --releasever=latest update
git clone https://github.com/JasonMossotti/dco-vendor-scorecard.git
cd dco-vendor-scorecard
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-app.txt
pytest -q                                  # confirm everything passes on this machine
streamlit run app/streamlit_app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true
```

Browse to `http://<instance-public-ip>:8501`.

**3. Keep it running as a service.** Create `/etc/systemd/system/dco-scorecard.service`:

```ini
[Unit]
Description=Unified Site Management scorecards (Streamlit)
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/dco-vendor-scorecard
ExecStart=/home/ec2-user/dco-vendor-scorecard/.venv/bin/streamlit run app/streamlit_app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now dco-scorecard
```

**4. Refresh the data every Monday.** The app automatically offers a "Latest 4 weeks" dataset when `data/latest/` exists. Create `/etc/systemd/system/dco-refresh.service`:

```ini
[Unit]
Description=Regenerate the latest 4 weeks of synthetic data

[Service]
Type=oneshot
User=ec2-user
WorkingDirectory=/home/ec2-user/dco-vendor-scorecard
ExecStart=/home/ec2-user/dco-vendor-scorecard/.venv/bin/python scripts/generate_data.py --latest --out data/latest
ExecStartPost=+/usr/bin/systemctl restart dco-scorecard
```

and `/etc/systemd/system/dco-refresh.timer`:

```ini
[Unit]
Description=Weekly data refresh (Mondays 06:00 UTC)

[Timer]
OnCalendar=Mon *-*-* 06:00:00 UTC
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now dco-refresh.timer
systemctl list-timers dco-refresh.timer     # confirm the next run
```

(Amazon Linux 2023 does not ship a cron daemon by default; systemd timers are the built-in equivalent.)

## C. Production architecture

At a real site, the scorecard would run against live systems instead of synthetic files. The code is already shaped for this: every data source sits behind one interface in `src/scorecard/connectors.py`, so production means writing connectors, not changing the engine.

```
 Site management network (out-of-band, private)         AWS account
 ┌───────────────────────────────────────────┐         ┌──────────────────────────────────────────┐
 │ BMC Redfish · DCGM/Prometheus · UFM · NMX │         │ Scheduled job (EventBridge Scheduler ->  │
 │ health checks · scheduler · badge system  │◄──VPN──►│ ECS task or EC2) runs engine + scorecard │
 └───────────────────────────────────────────┘         │   │                                      │
 Vendor ITSM API (tickets, roster, spares) ◄────HTTPS──┤   ├─► S3: reports, history (versioned)   │
                                                       │   ├─► SNS: same-day alert on S1 items    │
                                                       │   └─► CloudWatch: logs, job alarms       │
                                                       │ App behind ALB + HTTPS + SSO sign-in     │
                                                       └──────────────────────────────────────────┘
```

Key choices and why:

- **Collectors run close to the hardware.** BMCs, fabric managers, and health-check systems sit on an isolated management network, so collection runs inside it (or reaches it over a site-to-site VPN). It is never exposed to the internet.
- **Credentials in AWS Secrets Manager,** read through an IAM role with least privilege. Nothing in code or config files.
- **Read-only access to telemetry and the vendor's ITSM.** The scorecard observes; it never changes site systems.
- **Scheduled runs:** daily for findings, weekly for the operating scorecard, monthly for the Service Level Report, matching the SLA's governance cadence.
- **History in S3 with versioning,** so every scorecard and finding is reproducible during a dispute (the SLA's 5-business-day dispute window).
- **S1 items alert the same day** (SNS to the site lead and DCO leadership), matching the severity index's escalation rule.
- **The app requires sign-in** (an Application Load Balancer with HTTPS and an identity provider) because vendor performance data is commercially sensitive.
