#psql -c "CREATE EXTENSION postgis;"
psql -c "DROP TABLE IF EXISTS resolutions_scannage;"
psql -c "CREATE TABLE resolutions_scannage (ID_MISSTA varchar, RESOLUTION float, ID_MISPHOT varchar, Resolution_scan varchar);"
cat resolutions_scannage.csv | psql -c "COPY resolutions_scannage(ID_MISSTA, RESOLUTION, ID_MISPHOT, Resolution_scan) FROM STDIN DELIMITER ',' CSV HEADER"

psql -c "alter table resolutions_scannage alter column resolution_scan type float using translate(resolution_scan,'dp ','')::float"

