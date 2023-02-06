# Allegoria

## Create tables
cd docker-postgis
docker compose -f docker-compose-prod.build.yml --env-file .env build postgis-prod

cd docker-geoserver
docker compose up

## TODO copy install scripts in /scripts OR create db from scripts/setup-database.sh

docker exec -it misphot-db-1 /bin/bash
su postgres
psql -h localhost -U misphot gis
bash "create_views.sh"
bash "resolutions_scannage.sh"


## 
cd scripts
sudo mount -v -t cifs -o rw,user=mzellou,domain=IGN,uid=24162,gid=10000 //misphot-srv.ign.fr/misphot /media/misphot

export POSTGRES_USER=misphot
export POSTGRES_PASS=04L1an9rv1IyyKh4xgy3

python3 micmac2pg.py "/media/misphot/Lambert93/*/*/*.xml" 2154 $POSTGRES_USER $POSTGRES_PASS gis 172.20.0.52 49158

python3 ta2pg.py "/media/misphot/Lambert93/*/*/*.xml" $POSTGRES_USER $POSTGRES_PASS gis 172.20.0.52 49158

python3 ta2pg.py user password nomBDD host port