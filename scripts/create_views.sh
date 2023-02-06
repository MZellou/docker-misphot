
psql -c "
drop table IF EXISTS sources CASCADE;
CREATE TABLE IF NOT EXISTS sources (
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
CREATE INDEX sources_footprint_gix ON sources USING gist(footprint);
"

cat sources.csv | psql -c "COPY sources(tablename,credits,home,url,viewer,thumbnail,lowres,highres,iip) FROM STDIN DELIMITER ',' CSV HEADER"

psql -c "
drop table IF EXISTS masks CASCADE;
CREATE TABLE IF NOT EXISTS masks (
     id  SERIAL PRIMARY KEY,
     url VARCHAR
);
insert into masks(id, url) VALUES (0,NULL);
"

psql -c "
drop table IF EXISTS  georefs CASCADE;
CREATE TABLE IF NOT EXISTS georefs (
     id  SERIAL PRIMARY KEY, -- pg identifier
     source SERIAL REFERENCES sources(id), -- pg identifier of the source (credits, translation of uri to data urls...)
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
     mask SERIAL REFERENCES masks(id) -- id of the mask image (black white image masking image parts, such as vehicle parts or 'repere de fond de chambre')
);
CREATE INDEX georefs_point_gix ON georefs USING gist(p);

drop table IF EXISTS micmac_georefs_2154 CASCADE;
drop table IF EXISTS micmac_georefs_4978 CASCADE;
create table micmac_georefs_2154 as (select * from georefs) with no data;
alter table micmac_georefs_2154 alter column p type geometry(PointZ,2154);
create table micmac_georefs_4978 as (select * from georefs) with no data;
alter table micmac_georefs_4978 alter column p type geometry(PointZ,4978);
"

psql -c "
create or replace view IGN_georefs as select 
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

from cliches c, chantiers ch, sensors s, sources so where c.sensor=s.id and so.tablename ilike '%cliches%' and c.chantier=ch.id;
"

