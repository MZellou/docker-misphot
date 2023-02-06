# IGN specific
echo "Creating SCHEMA for misphot params"

PGPASSWORD=${POSTGRES_PASS} psql gis -U ${POSTGRES_USER} -p 5432 -h localhost -c "CREATE SCHEMA IF NOT EXISTS misphot;"

echo "Creating TABLES for misphot params"

PGPASSWORD=${POSTGRES_PASS} psql gis -U ${POSTGRES_USER} -p 5432 -h localhost -c "DROP TABLE IF EXISTS misphot.resolutions_scannage;"
PGPASSWORD=${POSTGRES_PASS} psql gis -U ${POSTGRES_USER} -p 5432 -h localhost -c "CREATE TABLE misphot.resolutions_scannage (ID_MISSTA varchar, RESOLUTION float, ID_MISPHOT varchar, Resolution_scan varchar);"
cat resolutions_scannage.csv | PGPASSWORD=${POSTGRES_PASS} psql gis -U ${POSTGRES_USER} -p 5432 -h localhost -c "COPY misphot.resolutions_scannage(ID_MISSTA, RESOLUTION, ID_MISPHOT, Resolution_scan) FROM STDIN DELIMITER ',' CSV HEADER"

PGPASSWORD=${POSTGRES_PASS} psql gis -U ${POSTGRES_USER} -p 5432 -h localhost -c "alter table misphot.resolutions_scannage alter column resolution_scan type float using translate(resolution_scan,'dp ','')::float"


PGPASSWORD=${POSTGRES_PASS} psql gis -U ${POSTGRES_USER} -p 5432 -h localhost -c "
drop table IF EXISTS misphot.sources CASCADE;
CREATE TABLE IF NOT EXISTS misphot.sources (
    id  SERIAL PRIMARY KEY,                                                      
    tablename VARCHAR,      
    credits VARCHAR,                                                  
    home VARCHAR,                                                      
    url VARCHAR,                                                            
    viewer VARCHAR,                                                  
    thumbnail VARCHAR,
    lowres VARCHAR,
    highres VARCHAR,
    iip VARCHAR,
    footprint geometry(MultiPolygon,2154)
);
CREATE INDEX sources_footprint_gix ON misphot.sources USING gist(footprint);
"

cat sources.csv | PGPASSWORD=${POSTGRES_PASS} psql gis -U ${POSTGRES_USER} -p 5432 -h localhost -c "COPY misphot.sources(tablename,credits,home,url,viewer,thumbnail,lowres,highres,iip) FROM STDIN DELIMITER ',' CSV HEADER"

PGPASSWORD=${POSTGRES_PASS} psql gis -U ${POSTGRES_USER} -p 5432 -h localhost -c "
drop table IF EXISTS misphot.masks CASCADE;
CREATE TABLE IF NOT EXISTS misphot.masks (
     id  SERIAL PRIMARY KEY,
     url VARCHAR
);
insert into misphot.masks(id, url) VALUES (0,NULL);
"

PGPASSWORD=${POSTGRES_PASS} psql gis -U ${POSTGRES_USER} -p 5432 -h localhost -c "
drop table IF EXISTS misphot.georefs CASCADE;

CREATE TABLE IF NOT EXISTS misphot.georefs (
     id SERIAL PRIMARY KEY, -- pg identifier
     source SERIAL REFERENCES misphot.sources(id), -- pg identifier of the source (credits, translation of uri to data urls...)
     t0 timestamp with time zone, -- earliest possible time of acquisition start
     t1 timestamp with time zone, -- latest possible time of acquisition end
     te timestamp with time zone, -- time of estimation / update in the database
     uri VARCHAR, -- uri of the image, to retrieve its data (pixel values) and metadata (triple store)
     p geometry(PointZ,0), -- camera center position
     qx FLOAT, -- quaternion x
     qy FLOAT, -- quaternion y
     qz FLOAT, -- quaternion z
     qw FLOAT, -- quaternion w
     fx FLOAT, -- focal length x (pixels)
     fy FLOAT, -- focal length y (pixels)
     px FLOAT, -- principal point x (pixels)
     py FLOAT, -- principal point y (pixels)
     sk FLOAT, -- skew
     sx INT, -- height (pixels)
     sy INT, -- width (pixels)
     cx FLOAT, -- distortion center x
     cy FLOAT, -- distortion center y
     c3 FLOAT, -- distortion radial coefficient r^3
     c5 FLOAT, -- distortion radial coefficient r^5
     c7 FLOAT, -- distortion radial coefficient r^7
     m00 FLOAT, -- affine image transform (linear part top left)
     m10 FLOAT, -- affine image transform (linear part top right)
     m20 FLOAT, -- affine image transform (translation x)
     m01 FLOAT, -- affine image transform (linear part bottom left)
     m11 FLOAT, -- affine image transform (linear part bottom right)
     m21 FLOAT, -- affine image transform (translation y)
     mask SERIAL REFERENCES misphot.masks(id) -- id of the mask image (black white image masking image parts, such as vehicle parts or 'repere de fond de chambre')
);
CREATE INDEX georefs_point_gix ON misphot.georefs USING gist(p);

drop table IF EXISTS misphot.micmac_georefs_2154 CASCADE;
create table misphot.micmac_georefs_2154 as (select * from misphot.georefs) with no data;
alter table misphot.micmac_georefs_2154 alter column p type geometry(PointZ,2154);

drop table IF EXISTS misphot.micmac_georefs_4978 CASCADE;
create table misphot.micmac_georefs_4978 as (select * from misphot.georefs) with no data;
alter table misphot.micmac_georefs_4978 alter column p type geometry(PointZ,4978);
"

PGPASSWORD=${POSTGRES_PASS} psql gis -U ${POSTGRES_USER} -p 5432 -h localhost -c "
CREATE TABLE IF NOT EXISTS misphot.chantiers (
	id  SERIAL PRIMARY KEY,
	t0 timestamp with time zone,
	t1 timestamp with time zone,
	footprint geometry(MultiPolygon,2154),
	resolution_scan float,
	resolution_image float,
	id_missta varchar,

	name VARCHAR,
	projection VARCHAR,
	MNT VARCHAR,
	Z0 FLOAT,
	derive FLOAT,
	overlap FLOAT,
	sidelap FLOAT,
	resolution FLOAT,
	overlap_delta FLOAT,
	sidelap_delta FLOAT,
	resolution_delta FLOAT,
	sun_height_min FLOAT,
	reference_alti VARCHAR,
	zi FLOAT,

	centre_rep_local geometry(Point,0),
	centre_rep_local_proj VARCHAR,
	centre_rep_local_proj_top_aero VARCHAR,
	centre_rep_local_srid_top_aero INT,

	apx_origine VARCHAR,
	nom_generique VARCHAR,
	designation VARCHAR,
	numero_SAA VARCHAR,
	theme VARCHAR,
	theme_geographique VARCHAR,
	commanditaire VARCHAR,
	producteur VARCHAR,
	style VARCHAR,
	emulsion VARCHAR,
	support VARCHAR,
	qualite VARCHAR,
	annee_debut INT,
	note VARCHAR,
	qualite_pva VARCHAR,
	ta_footprint geometry(MultiPolygon,0),

	process_date VARCHAR,
	process_version VARCHAR,
	ta_resolution FLOAT,
	context INT,
	redori VARCHAR,
	folder VARCHAR,

	ta_preparation_proj VARCHAR,
	ta_preparation_poly geometry(Polygon,0),
	
-- derived
	oblique BOOL not NULL default false
);

CREATE TABLE IF NOT EXISTS misphot.infos_mission (
	id  SERIAL PRIMARY KEY,
	chantier SERIAL REFERENCES misphot.chantiers(id) ON DELETE CASCADE,

	type INT,
	date VARCHAR,
	heure VARCHAR,
	info VARCHAR
);

CREATE TABLE IF NOT EXISTS misphot.ta_preparations (
	id  SERIAL PRIMARY KEY,
	chantier SERIAL REFERENCES misphot.chantiers(id) ON DELETE CASCADE,

	axe INT,
	altitude FLOAT,
	nbcli INT,
	line geometry(LineString,0),
	start_num INT,
	end_num INT
);

"

PGPASSWORD=${POSTGRES_PASS} psql gis -U ${POSTGRES_USER} -p 5432 -h localhost -c "
CREATE TABLE IF NOT EXISTS misphot.lots (
	id  SERIAL PRIMARY KEY,
	chantier SERIAL REFERENCES misphot.chantiers(id) ON DELETE CASCADE,

	name VARCHAR,
	type_gamma VARCHAR,
	rand_conversion INT,
	reference INT,
	bloc_type VARCHAR,
	apply INT,
	visible INT
);

CREATE TABLE IF NOT EXISTS misphot.lot_channel (
	id  SERIAL PRIMARY KEY,
	lot SERIAL REFERENCES misphot.lots(id),

	channel VARCHAR,
	niveau_max FLOAT,
	gamma FLOAT,
	voile FLOAT, 
	min_out FLOAT,
	max_out FLOAT
);

CREATE TABLE IF NOT EXISTS misphot.lot_bloc (
	id  SERIAL PRIMARY KEY,
	lot SERIAL REFERENCES misphot.lots(id),

	channel VARCHAR,
	a FLOAT,
	b FLOAT
);
"


PGPASSWORD=${POSTGRES_PASS} psql gis -U ${POSTGRES_USER} -p 5432 -h localhost -c "
CREATE TABLE IF NOT EXISTS misphot.vols (
	id       SERIAL PRIMARY KEY,
	chantier SERIAL REFERENCES misphot.chantiers(id) ON DELETE CASCADE,
	t0 timestamp with time zone,
	t1 timestamp with time zone,
	footprint geometry(MultiPolygon,2154),
	url VARCHAR,

	number INT,
	logname VARCHAR,
	mission VARCHAR,
	date VARCHAR,
	actif BOOL,
	qualite INT,
	note VARCHAR
);

CREATE TABLE IF NOT EXISTS misphot.meteo (
	id  SERIAL PRIMARY KEY,
	vol SERIAL REFERENCES misphot.vols(id),

	time FLOAT,
	nebulosite INT,
	visibilite FLOAT
);
"

PGPASSWORD=${POSTGRES_PASS} psql gis -U ${POSTGRES_USER} -p 5432 -h localhost -c "
DO \$$
BEGIN
	IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'disto_grid_type') THEN
		CREATE TYPE misphot.disto_grid_type AS (
			origine POINT,
			step POINT,
			step_is_adapted INT,
			x VARCHAR,
			y VARCHAR,
			size POINT
		);
	END IF;
END
\$$;

DO \$$
BEGIN
	IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'disto_radial_type') THEN
		CREATE TYPE misphot.disto_radial_type AS (
			x FLOAT,
			y FLOAT,
			c3 FLOAT,
			c5 FLOAT,
			c7 FLOAT
		);
	END IF;
END
\$$;

CREATE TABLE IF NOT EXISTS misphot.sensors (
	id       SERIAL PRIMARY KEY,
	vol      SERIAL REFERENCES misphot.vols(id),
	chantier SERIAL REFERENCES misphot.chantiers(id) ON DELETE CASCADE,
	footprint geometry(MultiPolygon,2154),

-- sensor sytem 
	actif BOOL,
	avion VARCHAR,
	omega FLOAT,
	phi FLOAT,
	kappa FLOAT,
	refraction FLOAT,
	trappe BIGINT,
	antenne geometry(PointZ,0),

-- sensor
	name VARCHAR,
	objectif VARCHAR,
	origine VARCHAR,
	argentique BOOL,
	calibration_date VARCHAR,
	serial_number VARCHAR,
	usefull_frame BOX,
	dark_frame BOX,
	dark_frame_zone VARCHAR,
	-- defect
	focal_x FLOAT,
	focal_y FLOAT,
	focal_z FLOAT,
	disto_radial misphot.disto_radial_type,
	disto_grid_fwd misphot.disto_grid_type,
	disto_grid_bwd misphot.disto_grid_type,
	pixel_size FLOAT,
	orientation INT,
	scan_width FLOAT,
	wb_channel VARCHAR,
	wb_coef FLOAT,
	wb_ref VARCHAR,
	file_origine VARCHAR
);

CREATE TABLE IF NOT EXISTS misphot.defects (
	id       SERIAL PRIMARY KEY,
	sensor   SERIAL REFERENCES misphot.sensors(id),
	type VARCHAR,
	box BOX,
	value FLOAT
);

"""

PGPASSWORD=${POSTGRES_PASS} psql gis -U ${POSTGRES_USER} -p 5432 -h localhost -c "
CREATE TABLE IF NOT EXISTS misphot.bandes (
	id  SERIAL PRIMARY KEY,
	vol SERIAL REFERENCES misphot.vols(id),
	chantier SERIAL REFERENCES misphot.chantiers(id) ON DELETE CASCADE,
	t0 timestamp with time zone,
	t1 timestamp with time zone,
	footprint geometry(MultiPolygon,2154),
	trajectory geometry(LineStringZ,2154),

	number INT,
	axe INT,
	actif BOOL,
	trans FLOAT,
	kappa FLOAT,
	a FLOAT,
	b FLOAT,
	c FLOAT,
	nb_section INT,
	altitude FLOAT,
	qualite INT,
	note VARCHAR,
	start_time FLOAT,
	end_time FLOAT,
	nb_cli_declare INT
);
"

PGPASSWORD=${POSTGRES_PASS} psql gis -U ${POSTGRES_USER} -p 5432 -h localhost -c "
CREATE TABLE IF NOT EXISTS misphot.cliches (
	id  SERIAL PRIMARY KEY,
	bande SERIAL REFERENCES misphot.bandes(id),
	vol SERIAL REFERENCES misphot.vols(id),
	chantier SERIAL REFERENCES misphot.chantiers(id) ON DELETE CASCADE,
	sensor SERIAL REFERENCES misphot.sensors(id),
	lot INT NULL REFERENCES misphot.lots(id),
	t0 timestamp with time zone,
	t1 timestamp with time zone,
	url VARCHAR,

	image VARCHAR,
	origine VARCHAR,
	nb_canaux INT,
	number INT,
	modhs_type VARCHAR,
	actif BOOL,
	zi INT,
	qualite INT,
	note VARCHAR,
	time FLOAT,
	sun_height FLOAT,
	pose FLOAT,
	tdi FLOAT,
	section INT,
	nav_interpol BOOL,
	style INT,
	resolution_moy FLOAT,
	resolution_min FLOAT,
	resolution_max FLOAT,
	overlap     FLOAT,
	overlap_max FLOAT,
	overlap_min FLOAT,
	footprint geometry(Polygon,2154), -- polygon2d 
	point geometry(PointZ,2154), -- pt3d
	quaternion geometry(PointZM,0),
	systbde INT,
	systbde_a FLOAT,
	systbde_b FLOAT,
	lock BOOL,
	nadir geometry(PointZ,2154),
	trajecto geometry(PointZ,2154),
	indicator FLOAT,
	indicator_type VARCHAR,
	platf_b FLOAT,
	platf_e FLOAT,
	platf_d FLOAT
);

CREATE TABLE IF NOT EXISTS misphot.modhs (
	id  SERIAL PRIMARY KEY,
	cliche SERIAL REFERENCES misphot.cliches(id),

	channel VARCHAR,
	k FLOAT,
	e FLOAT,
	a FLOAT,
	hsmin FLOAT
);
"


PGPASSWORD=${POSTGRES_PASS} psql gis -U ${POSTGRES_USER} -p 5432 -h localhost -c "
create or replace view misphot.IGN_georefs as select 
     c.id as id,
     so.id as source,
     c.t0,
     c.t1,
     c.t1 as te,
     c.url as uri,
     point as p,
     (-st_x(quaternion)-st_y(quaternion))/sqrt(2.0) as qx,
     (+st_x(quaternion)-st_y(quaternion))/sqrt(2.0) as qy,
     (-st_m(quaternion)-st_z(quaternion))/sqrt(2.0) as qz,
     (-st_m(quaternion)+st_z(quaternion))/sqrt(2.0) as qw,

     focal_z*coalesce(resolution_scan/25.4,1.) as fx,
     focal_z*coalesce(resolution_scan/25.4,1.) as fy,
     focal_x*coalesce(resolution_scan/25.4,1.) as px,
     focal_y*coalesce(resolution_scan/25.4,1.) as py,
     
     0::float as sk,
     (2*focal_x*coalesce(resolution_scan/25.4,1.))::int as sx,
     (2*focal_y*coalesce(resolution_scan/25.4,1.))::int as sy,
     
     (s.disto_radial).x as cx,
     (s.disto_radial).y as cy,
     (s.disto_radial).c3 as c3,
     (s.disto_radial).c5 as c5,
     (s.disto_radial).c7 as c7,
     
     NULL::float as m00,
     NULL::float as m10,
     NULL::float as m20,
     NULL::float as m01,
     NULL::float as m11,
     NULL::float as m21,
     
     0 as mask

from misphot.cliches c, misphot.chantiers ch, misphot.sensors s, misphot.sources so where c.sensor=s.id and so.tablename ilike '%cliches%' and c.chantier=ch.id;
"

PGPASSWORD=${POSTGRES_PASS} psql gis -U ${POSTGRES_USER} -p 5432 -h localhost -c "
create index if not exists cliches_bande_idx on misphot.cliches(bande);
create index if not exists cliches_sensor_idx on misphot.cliches(sensor);
create index if not exists cliches_vol_idx on misphot.cliches(vol);
create index if not exists cliches_chantier_idx on misphot.cliches(chantier);
create index if not exists bandes_vol_idx on misphot.bandes(vol);
create index if not exists bandes_chantier_idx on misphot.bandes(chantier);
create index if not exists sensors_vol_idx on misphot.sensors(vol);
create index if not exists vols_chantier_idx on misphot.vols(chantier);

create index if not exists chantiers_footprint_idx on misphot.chantiers using gist(footprint);
create index if not exists vols_footprint_idx on misphot.vols using gist(footprint);
create index if not exists sensors_footprint_idx on misphot.sensors using gist(footprint);
create index if not exists bandes_footprint_idx on misphot.bandes using gist(footprint);
create index if not exists bandes_trajectory_idx on misphot.bandes using gist(trajectory);
create index if not exists cliches_footprint_idx on misphot.cliches using gist(footprint);
create index if not exists cliches_point_idx on misphot.cliches using gist(point);
create index if not exists cliches_nadir_idx on misphot.cliches using gist(nadir);
create index if not exists cliches_trajecto_idx on misphot.cliches using gist(trajecto);
create index if not exists ta_preparations_line_idx on misphot.ta_preparations using gist(line);
"