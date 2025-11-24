#!/bin/sh

host="$1"
shift

echo "Waiting for postgres at host: $host ..."

until nc -z "$host" 5432; do
  echo "Postgres is unavailable - sleeping"
  sleep 1
done

echo "Postgres is up - executing command"
exec "$@"
