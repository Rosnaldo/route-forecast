# nginx

All nginx configuration for the project.

```
nginx/
├── .env.dev                     BASE_DOMAIN, ADMIN_EMAIL for development
├── .env.prod                    BASE_DOMAIN, ADMIN_EMAIL for production
├── dev/
│   ├── nginx.conf               docker-compose.yml → nginx
│   └── certs/                   mkcert certificates (git-ignored)
└── prod/
    ├── http/nginx.conf          docker-compose.prod.yml → nginx-http
    ├── https/nginx.conf         docker-compose.prod.yml → nginx-https (also serves the React app)
    ├── certbot/                 ACME challenge files (git-ignored)
    └── letsencrypt/             Let's Encrypt certificates (git-ignored)
```

Each `nginx.conf` is mounted as `/etc/nginx/templates/default.conf.template` (the
name the nginx image looks for). When the container
starts, the nginx image fills in `${BASE_DOMAIN}` from the env file and writes the
result to `/etc/nginx/conf.d/default.conf`. Only variables that are set get replaced,
so nginx's own variables (`$host`, `$scheme`, ...) stay as they are.

## Development

HTTPS on your machine with a locally trusted certificate made by
[mkcert](https://github.com/FiloSottile/mkcert):

```sh
sudo apt install libnss3-tools
curl -JLO "https://dl.filippo.io/mkcert/latest?for=linux/amd64"
chmod +x mkcert-v*-linux-amd64
sudo mv mkcert-v*-linux-amd64 /usr/local/bin/mkcert
mkcert -install

# One certificate for BASE_DOMAIN (nginx/.env.dev), named as the template expects:
# <domain>.pem and <domain>-key.pem
mkdir -p nginx/dev/certs && cd nginx/dev/certs && mkcert localhost
```

If you use a domain other than `localhost`, set it as `BASE_DOMAIN`, run
`mkcert <domain>` instead and add it to `/etc/hosts`:

```
127.0.0.1 <domain> www.<domain>
```

Then run `docker compose up --build` and open `https://<BASE_DOMAIN>`.

## Production

1. Point DNS A records for `BASE_DOMAIN` and `www.BASE_DOMAIN` to the server.
2. Set `BASE_DOMAIN` and `ADMIN_EMAIL` (Let's Encrypt's expiry notices) in
   `nginx/.env.prod`. In the root `.env`, add the domain to `ALLOWED_HOSTS` and
   `https://<domain>` to `CSRF_TRUSTED_ORIGINS`.
3. `docker compose -f docker-compose.prod.yml up -d --build`

How the certificate is obtained and kept:

- `nginx-http` (port 80) serves `/.well-known/acme-challenge/` from `prod/certbot/`
  and redirects everything else to HTTPS.
- `certbot` runs once per `up`: it proves control of the domain by writing the
  challenge file that nginx-http serves, then stores the certificate in
  `prod/letsencrypt/`. Later runs do nothing until the certificate is close to expiry.
- `nginx-https` (port 443) needs that certificate. On the first deploy it restarts
  until certbot has written it.
- `certbot-renew` tries to renew every 12 hours. Certificates are renewed within 30
  days of expiry, and `nginx-https` reloads every 6 hours to pick up the new one.
