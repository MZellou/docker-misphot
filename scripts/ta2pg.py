import sys
import psycopg2
from psycopg2.extras import execute_values
import xml.etree.ElementTree as ET
import glob

filename = sys.argv[1] if len(sys.argv) > 1 else "*.xml"
user     = sys.argv[2] if len(sys.argv) > 2 else None
password = sys.argv[3] if len(sys.argv) > 3 else None
database = sys.argv[4] if len(sys.argv) > 4 else None
host     = sys.argv[5] if len(sys.argv) > 5 else None
port     = sys.argv[6] if len(sys.argv) > 6 else None
debug = False

refresh_timestamp_columns = """
-- correct ambiguous misphot.vols.date (2261919 => 22061919, 9062004 => 09062004)
UPDATE misphot.vols set date=concat(substr(date,1,2),'0',substr(date,3)) where chantier={0} and length(date)=7 and substr(date,2,2)::int > 12;

-- extract misphot.vols.t0/t1 at the beginning/end of the day,month or year (depending on the date precision)
UPDATE misphot.vols set t0 = to_timestamp(lpad(date,8,'00001900'),'DDMMYYYY') where chantier={0};
UPDATE misphot.vols set t1 = t0 + interval '1 day'   where chantier={0} and length(date)>6;
UPDATE misphot.vols set t1 = t0 + interval '1 month' where chantier={0} and length(date)=5 or length(date)=6;
UPDATE misphot.vols set t1 = t0 + interval '1 year'  where chantier={0} and length(date)<5;

-- clear misphot.vols.t0 and t1 for dummy dates (<1900)
UPDATE misphot.vols SET t0 = NULL, t1 = NULL where chantier={0} and extract(year from t0) < 1900;

-- propagate t0/t1 from misphot.vols to misphot.bandes and misphot.cliches
UPDATE misphot.bandes  SET t0=v.t0, t1=v.t1 from misphot.vols v where misphot.bandes.chantier={0} and v.chantier={0} and v.id=vol;
UPDATE misphot.cliches SET t0=v.t0, t1=v.t1 from misphot.vols v where misphot.cliches.chantier={0} and v.chantier={0} and v.id=vol;

-- evaluate misphot.cliches.time
UPDATE misphot.cliches SET
	t0= b.t0 + make_interval(0,0,0, 0,floor(time/10000)::int,floor(time/100)::int % 100,mod(time::numeric,100.)),
	t1= b.t1 + make_interval(0,0,0,-1,floor(time/10000)::int,floor(time/100)::int % 100,mod(time::numeric,100.))
from misphot.bandes b where misphot.cliches.chantier={0} and b.chantier={0} and b.id=bande and time is not null;

-- compute the chantier timestamps
UPDATE misphot.bandes    SET t0=q.t0, t1=q.t1 from (select min(t0) as t0, max(t1) as t1, bande from misphot.cliches where chantier={0} group by bande) as q where chantier={0} and id=q.bande;
UPDATE misphot.vols      SET t0=q.t0, t1=q.t1 from (select min(t0) as t0, max(t1) as t1, vol from misphot.bandes  where chantier={0} group by vol) as q where chantier={0} and id=q.vol;
UPDATE misphot.chantiers SET t0=q.t0, t1=q.t1 from (select min(t0) as t0, max(t1) as t1 from misphot.vols where chantier={0}) as q where id={0};
"""

refresh_url_columns = """
update misphot.vols set url =
  c.nom_generique || '/IGNF_PVA_1-0__' ||
  replace(regexp_replace(lpad(misphot.vols.date,8,'0'),'(..)(..)(....)','\\3-\\2-\\1'),'-00','') ||
  '__C' || c.nom_generique || '_'
from misphot.chantiers c where c.id={0} and misphot.vols.chantier={0};

update misphot.cliches set url = v.url || image || '.jp2' from misphot.vols v where misphot.cliches.chantier={0} and misphot.cliches.vol = v.id;
"""

refresh_geometry_columns = """
UPDATE misphot.cliches SET footprint=NULL where chantier={0} and (st_xmax(footprint)=-1 or st_area(footprint)=0);

UPDATE misphot.bandes SET footprint=q.f, trajectory=q.t from (select
 st_multi(st_union(footprint)) as f,
 st_makeline(point ORDER BY number) as t,
 bande from misphot.cliches where chantier={0} group by bande) as q where chantier={0} and q.bande=id;

UPDATE misphot.sensors SET footprint=q.f from (select
 st_multi(st_union(footprint)) as f, sensor from misphot.cliches where chantier={0} GROUP BY sensor) as q where chantier={0} and q.sensor=id;
 
update misphot.vols set footprint=q.f from (select
 st_multi(st_union(footprint)) as f, vol    from misphot.bandes  where chantier={0} GROUP BY vol) as q where chantier={0} and q.vol=id;
 
update misphot.chantiers set footprint=q.f from (select
 st_multi(st_union(footprint)) as f from misphot.vols  where chantier={0} GROUP BY chantier) as q where id={0};
"""


refresh_chantiers_columns = """
update misphot.chantiers set
	id_missta = r.id_missta,
	resolution_image = r.resolution,
	resolution_scan = r.resolution_scan
from misphot.resolutions_scannage r where id={0} and nom_generique = id_misphot;

update misphot.chantiers set oblique = note ilike '%mission%oblique%' where note is not null and id={0};
"""


def find(node, *tags):
	for tag in tags:
		if node is not None and tag is not None:
			node = node.find(tag)
	return node

def get_srid(proj):
	proj = proj and ''.join(proj.split()).lower() # remove spaces and make it lowercase
	srid_dict = {
		'lambert93' : 2154
	}
	return srid_dict.get(proj) or 0

def valueS(node, tag):
	node = find(node,tag)
	return None if (node is None or node.text is None) else (node.text.strip() or None)

def valueI(node, tag):
	s = valueS(node,tag)
	return None if s is None else int(s)

def valueF(node, tag):
	s = valueS(node,tag)
	return None if s is None else float(s)

def valueB(node, tag):
	s = valueS(node,tag)
	return None if s is None else s == '1'

def valueP(node, tag):
	p = find(node,tag)
	return None if p is None else '({},{})'.format(valueF(p,'x'),valueF(p,'y'))

def valueR(node, tag1, tag2 = None):
	node = find(node,tag1,tag2)
	if node is None:
		return None
	x = valueF(node,'x')
	y = valueF(node,'y')
	w = valueF(node,'w')
	h = valueF(node,'h')
	return '({},{},{},{})'.format(x,y,x+w,y+h)


def valuePoint(node, tag, srid = 0, raw = False):
	node = find(node,tag)
	if node is None:
		return None
	x = valueF(node,'x')
	y = valueF(node,'y')
	if raw:
		return '{} {}'.format(x,y)
	return 'SRID={};POINT({} {})'.format(srid,x,y)

def valueLineString(p1, p2, srid):
	if p1 is None or p2 is None:
		return None
	c1 = valuePoint(p1,'pt2d',0,True)
	c2 = valuePoint(p2,'pt2d',0,True)
	return 'SRID={};LINESTRING({},{})'.format(srid,c1,c2)

def valuePointZ(node, tag1, srid, tag2 = None):
	node = find(node,tag1,tag2)
	if node is None:
		return None
	x = valueF(node,'x')
	y = valueF(node,'y')
	z = valueF(node,'z')
	return 'SRID={};POINTZ({} {} {})'.format(srid,x,y,z)


def valuePointZM(node, tag, srid):
	node = find(node,tag)
	if node is None:
		return None
	x = valueF(node,'x')
	y = valueF(node,'y')
	z = valueF(node,'z')
	w = valueF(node,'w')
	return 'SRID={};POINTZM({} {} {} {})'.format(srid,x,y,z,w),


def valuePolygon(node, tag, srid, raw = False, tag2 = None):
	node = find(node,tag,tag2)
 
	if node is None:
		return None

	x = node.findall('x')
	y = node.findall('y')

	hole = valueB(node,'hole') or False
	if len(x) != len(y):
		print("x.length != y.length in <{}>".format(tag))
		return None

	if len(x) == 0:
		print("x.length == 0 in <{}>".format(tag))
		return None
	# //!!\\
	coordinates = []
 
	for i in range(0,len(x)):
		coordinates.append(x[i].text.strip() + ' ' + y[i].text.strip())
	coordinates.append(coordinates[0])
 
	coords = ','.join(coordinates)
 
	if raw:
		return hole, '({})'.format(coords)

	return 'SRID={};POLYGON(({}))'.format(srid,coords)

def valueMultiPolygon(node, tag, ring_tag, srid):
	node = find(node,tag)
	if node is None:
		return None
	multi = []
	poly  = None
	for n in node.findall(ring_tag):
		hole, ring = valuePolygon(n,None,srid,True)
		if hole:
			poly += ',{}'.format(ring)
		else:
			if poly:
				multi.append('({})'.format(poly))
			poly = ring
	if poly:
		multi.append('({})'.format(poly))
	return 'SRID={};MULTIPOLYGON({})'.format(srid,','.join(multi)) if multi else None

def valueDistortionRadial(node, tag):
	n = find(node,tag)
	p = find(n,'pt2d')
	if p is None:
		return None
	x = valueF(p,'x')
	y = valueF(p,'y')
	r3 = valueF(n,'r3')
	r5 = valueF(n,'r5')
	r7 = valueF(n,'r7')
	return '({},{},{},{},{})'.format(x,y,r3,r5,r7)

def valueDistortionGrid(g, tag1, tag2):
	g = find(g,tag1,tag2)
	if not g:
		return None
	origine = valueP(g,'origine')
	step = valueP(g,'step')
	step_is_adapted = valueI(g,'StepIsAdapted')
	f = find(g,'filename')
	x = valueS(f,'x')
	y = valueS(f,'y')
	size = valueP(g,'size')
	return '("{}","{}",{},"{}","{}","{}")'.format(origine,step,step_is_adapted,x,y,size)

def parseModhs(node, srid):
	return {
		'channel' : valueS(node,'channel'),
		'k'       : valueF(node, 'k'),
		'e'       : valueF(node, 'e'),
		'a'       : valueF(node, 'a'),
		'hsmin'   : valueF(node, 'hsmin')
	}

def parseDefect(node,srid):
	return {
		'type' : valueS(node,'type'),
		'box'  : valueR(node, 'rect'),
		'value': valueF(node, 'value')
	}

def parseChannel(node,srid):
	return {
		'channel':	valueS(node,'channel'),
		'niveau_max':	valueF(node, 'niveau_max'),
		'gamma':	valueF(node, 'gamma'),
		'voile':	valueF(node, 'voile'),
		'min_out':	valueF(node, 'min_out'),
		'max_out':	valueF(node, 'max_out')
	}



def parseBloc(node,srid):
	return {
		'channel'       : valueS(node, 'channel'),
		'A' : valueF(node, 'A'),
		'B' : valueF(node, 'B')
	}


def parseMeteo(node,srid):
	return {
		'time'       : valueF(node, 'time'),
		'nebulosite' : valueI(node, 'nebulosite'),
		'visibilite' : valueF(node, 'visibilite')
	}

def parsePrep(prep, srid):
	p1 = find(prep,'start')
	p2 = find(prep,'end')
	return {
		'axe'       : valueI(prep,'axe'),
		'altitude'  : valueF(prep, 'altitude'),
		'nbcli'     : valueI(prep, 'nbcli'),
		'line'      : valueLineString(p1, p2, srid),
		'start_num' : valueI(p1, 'num'),
		'end_num'   : valueI(p2, 'num')
	}

def parseInfo(info,srid):
	return {
		'type'  : valueI(info, 'type'),
		'date'  : valueS(info, 'date'),
		'heure' : valueS(info, 'heure'),
		'info'  : valueS(info, 'info')
	}

def parseCliche(cliche, srid):
	modhs = find(cliche,'modhs')
	indicator = find(cliche,'indicator')
	model = find(cliche,'model')
	systbde = find(model,'systbde')
	platf = find(cliche,'platf_info')
	return {
		'image'	  : valueS(cliche,'image'),
		'origine'	: valueS(cliche,'origine'),
		'nb_canaux'      : valueI(cliche,'nb_canaux'),
		'number'	 : valueI(cliche,'number'),
		'lot'	    : valueI(cliche,'lot'),
		'modhs_type'     : valueS(modhs,'type'),
		'actif'	  : valueB(cliche,'actif'),
		'zi'	     : valueI(cliche,'zi'),
		'qualite'	: valueI(cliche,'qualite'),
		'note'	   : valueS(cliche,'note'),
		'time'	   : valueF(cliche,'time'),
		'sun_height'     : valueF(cliche,'sun_height'),
		'pose'	   : valueF(cliche,'pose'),
		'tdi'	    : valueF(cliche,'tdi'),
		'section'	: valueI(cliche,'section'),
		'nav_interpol'   : valueB(cliche,'nav_interpol'),
		'style'	  : valueI(cliche,'style'),
		'resolution_moy' : valueF(cliche,'resolution_moy'),
		'resolution_min' : valueF(cliche,'resolution_min'),
		'resolution_max' : valueF(cliche,'resolution_max'),
		'overlap'	: valueF(cliche,'overlap'),
		'overlap_max'    : valueF(cliche,'overlap_max'),
		'overlap_min'    : valueF(cliche,'overlap_min'),
		'footprint'      : valuePolygon(cliche,'polygon2d',srid),
		'point'	  : valuePointZ(model,'pt3d',srid),
		'quaternion'     : valuePointZM(model,'quaternion',0),
		'systbde'	: valueI(systbde,'Type'),
		'systbde_a'      : valueF(systbde,'CylA'),
		'systbde_b'      : valueF(systbde,'CylB'),
		'lock'	   : valueB(model,'lock'),
		'nadir'	  : valuePointZ(cliche,'nadir',srid,'pt3d'),
		'trajecto'       : valuePointZ(cliche,'trajecto',srid,'pt3d'),
		'indicator'      : valueF(indicator,'value'),
		'indicator_type' : valueS(indicator,'type'),
		'platf_b'	: valueF(platf,'B'),
		'platf_e'	: valueF(platf,'E'),
		'platf_d'	: valueF(platf,'D'),
	}

def parseBande(bande):
	return {
		'number'	: valueI(bande,'number'),
		'axe'	   : valueI(bande,'axe'),
		'actif'	 : valueB(bande,'actif'),
		'trans'	 : valueF(bande,'trans'),
		'kappa'	 : valueF(bande,'kappa'),
		'a'	     : valueF(bande,'a'),
		'b'	     : valueF(bande,'b'),
		'c'	     : valueF(bande,'c'),
		'nb_section'    : valueI(bande,'nb_section'),
		'altitude'      : valueF(bande,'altitude'),
		'qualite'       : valueI(bande,'qualite'),
		'note'	  : valueS(bande,'note'),
		'start_time'    : valueF(bande,'start_time'),
		'end_time'      : valueF(bande,'end_time'),
		'nb_cli_declare': valueI(bande,'nb_cli_declare')
	}


def parseChantier(root):
	chantier       = find(root,'chantier')
	prep	   = find(root,'ta_preparation')
	projection     = valueS(chantier,      'projection')
	projection_ta  = valueS(prep,'projection')
	srid	   = get_srid(projection)
	srid_ta	= get_srid(projection_ta)

	centre_rep_local	 = find(chantier,'centre_rep_local')
	centre_rep_local_proj    = valueS(centre_rep_local,'proj')
	centre_rep_local_proj_ta = valueS(centre_rep_local,'projTopAero')
	centre_rep_local_srid    = get_srid(centre_rep_local_proj)
	centre_rep_local_srid_ta = get_srid(centre_rep_local_proj_ta)

	return srid, srid_ta, {
# TA
		'process_version' : valueS(root,'process-version'),
		'process_date'    : valueS(root,'process-date'),
# Chantier
		'name'	       : valueS(chantier,'nom'),

		'projection'	 : projection,
		'MNT'		: valueS(chantier,'MNT'),
		'Z0'		 : valueF(chantier,'Z0'),
		'derive'	     : valueF(chantier,'derive'),
		'overlap'	    : valueF(chantier,'overlap'),
		'sidelap'	    : valueF(chantier,'sidelap'),
		'resolution'	 : valueF(chantier,'resolution'),
		'sidelap'	    : valueF(chantier,'sidelap'),
		'overlap_delta'      : valueF(chantier,'overlap_delta'),
		'sidelap_delta'      : valueF(chantier,'sidelap_delta'),
		'resolution_delta'   : valueF(chantier,'resolution_delta'),
		'sun_height_min'     : valueF(chantier,'sun_height_min'),
		'sidelap_delta'      : valueF(chantier,'sidelap_delta'),
		'reference_alti'     : valueS(chantier,'reference_alti'),
		'zi'		 : valueF(chantier,'zi'),

		'centre_rep_local'	       : valuePoint(centre_rep_local,'pt2d',centre_rep_local_srid),
		'centre_rep_local_proj'	  : centre_rep_local_proj,
		'centre_rep_local_proj_top_aero' : centre_rep_local_proj_ta,
		'centre_rep_local_srid_top_aero' : centre_rep_local_srid_ta,

		'apx_origine'	: valueS(chantier,'apx_origine'),
		'nom_generique'      : valueS(chantier,'nom_generique'),
		'designation'	: valueS(chantier,'designation'),
		'numero_SAA'	 : valueS(chantier,'numero_SAA'),
		'theme'	      : valueS(chantier,'theme'),
		'theme_geographique' : valueS(chantier,'theme_geographique'),
		'commanditaire'      : valueS(chantier,'commanditaire'),
		'producteur'	 : valueS(chantier,'producteur'),
		'style'	      : valueS(chantier,'style'),
		'emulsion'	   : valueS(chantier,'emulsion'),
		'support'	    : valueS(chantier,'support'),
		'qualite'	    : valueS(chantier,'qualite'),
		'annee_debut'	: valueI(chantier,'annee_debut'),
		'note'	       : valueS(chantier,'note'),
		'qualite_pva'	: valueS(chantier,'qualite_pva'),
		'ta_footprint'       : valueMultiPolygon(chantier,'poly_contour','contour',srid),
# TA
		'ta_resolution'      : valueF(root,'resolution'),
		'context'	    : valueI(root,'context'),
		'redori'	     : valueS(root,'redori'),
		'folder'	     : valueS(root,'folder'),
		'ta_preparation_proj': projection_ta,
		'ta_preparation_poly': valuePolygon(prep,'poly_contour',srid_ta,False,'contour'),
	}


def parseSensor(node):
	sensor = find(node,'sensor')
	focal = find(sensor,'focal','pt3d')
	dark_frame = find(sensor,'dark-frame')
	whitebalance = find(sensor,'radiometry','whitebalance')
	doublegrid = find(sensor,'doublegrid')
	return {
		'actif'	   : valueB(node,'actif'),
		'avion'	   : valueS(node,'avion'),
		'omega'	   : valueF(node,'omega'),
		'phi'	     : valueF(node,'phi'),
		'kappa'	   : valueF(node,'kappa'),
		'refraction'      : valueF(node,'refraction'),
		'trappe'	  : valueI(node,'trappe'),
		'antenne'	 : valuePointZ(node,'rattachement_antenne',0,'pt3d'),

		'name'	    : valueS(sensor,'name'),
		'objectif'	: valueS(sensor,'objectif'),
		'origine'	 : valueS(sensor,'origine'),
		'argentique'      : valueB(sensor,'argentique'),
		'calibration_date': valueS(sensor,'calibration-date'),
		'serial_number'   : valueS(sensor,'serial-number'),
		'usefull_frame'   : valueR(sensor,'usefull-frame', 'rect'),
		'dark_frame'      : valueR(dark_frame,'rect'),
		'dark_frame_zone' : valueS(dark_frame,'apply-zone'),
		'focal_x'	 : valueF(focal,'x'),
		'focal_y'	 : valueF(focal,'y'),
		'focal_z'	 : valueF(focal,'z'),
		'disto_radial'    : valueDistortionRadial(sensor,'distortion'),
		'disto_grid_fwd'  : valueDistortionGrid(doublegrid,'grid_directe','grid'),
		'disto_grid_bwd'  : valueDistortionGrid(doublegrid,'grid_inverse','grid'),
		'pixel_size'      : valueF(sensor,'pixel_size'),
		'orientation'     : valueI(sensor,'orientation'),
		'scan_width'      : valueF(sensor,'scan_width'),
		'wb_channel'      : valueS(whitebalance,'canal'),
		'wb_coef'	 : valueF(whitebalance,'wb_coef'),
		'wb_ref'	  : valueS(whitebalance,'origine_ref'),
		'file_origine'    : valueS(sensor,'file_origine')
	}

def parseVol(node):
	return {
		'number'  : valueI(node,'number'),
		'logname' : valueS(node,'logname'),
		'mission' : valueS(node,'mission'),
		'date'    : valueI(node,'date'),
		'actif'   : valueB(node,'actif'),
		'qualite' : valueI(node,'qualite'),
		'note'    : valueS(node,'note')
	}


def parseLot(node):
	ModeleBloc = find(node,'ModeleBloc')
	return {
		'name'  : valueS(node,'name'),
		'type_gamma' : valueS(node,'type_gamma'),
		'rand_conversion' : valueI(node,'rand_conversion'),
		'reference'    : valueI(node,'reference'),
		'bloc_type' : valueS(ModeleBloc,'TypeModeleBloc'),
		'apply' :  valueI(node,'apply'),
		'visible' :  valueI(node,'visible'),
	}


def insertTable(table, parse, node, cursor, parent_id, parent, tag1, tag2, srid = None):
	node1 = find(node,tag1)
	if node1 is None:
		return []
	keys = []
	values = []
	for node2 in node1.findall(tag2):
		d = parse(node2, srid)
		d[parent] = parent_id
		keys = list(d.keys())
		values.append(list(d.values()))

	sql = """INSERT INTO misphot.{} ({}) VALUES %s""".format(table,','.join(keys))

	if debug: print(sql)
	result = execute_values(cursor, sql, values, fetch=False)
	return values


def insertSensors(vol, cursor, chantier_id, vol_id):
	keys = []
	values = []
	for sensor in vol.findall('system_sensor'):
		d = parseSensor(sensor)
		d['vol'] = vol_id
		d['chantier'] = chantier_id
		keys = list(d.keys())
		values.append(list(d.values()))

	sql = """
	INSERT INTO misphot.sensors ({})
	VALUES
	%s
	RETURNING id,name,origine
	""".format(','.join(keys))

	if debug: print(sql)
	result = execute_values(cursor, sql, values, fetch=True)

	for (i, sensor) in enumerate(vol.findall('system_sensor')):
		insertTable('defects',parseDefect, sensor, cursor, result[i][0], 'sensor', 'sensor', 'defect')

	return dict([(origine,id) for (id,name,origine) in result] + [(name,id) for (id,name,origine) in result])



def insertCliches(bande, cursor, chantier_id, lot_id, vol_id, bande_id, sensors, srid):
	keys = []
	values = []
	for cliche in bande.findall('cliche'):
		d = parseCliche(cliche, srid)
		l = d['lot']
		d['bande'] = bande_id
		d['sensor'] = sensors.get(d['origine'])
		d['vol'] = vol_id
		d['lot'] = None if l is None else lot_id[l-1]
		d['chantier'] = chantier_id
		keys = list(d.keys())
		values.append(list(d.values()))

	sql = """
	INSERT INTO misphot.cliches ({})
	VALUES
	%s
	RETURNING id
	""".format(','.join(keys))

	if debug: print(sql)
	result = execute_values(cursor, sql, values, fetch=True)
	cliche_id = [id for (id,) in result]

	for (i, cliche) in enumerate(bande.findall('cliche')):
		insertTable('modhs',parseModhs, cliche, cursor, cliche_id[i], 'cliche', 'modhs', 'paramshs')

	return cliche_id


def insertBandes(vol, cursor, chantier_id, lot_id, vol_id, sensors, srid):
	keys = []
	values = []
	for bande in vol.findall('bande'):
		d = parseBande(bande)
		d['vol'] = vol_id
		d['chantier'] = chantier_id
		keys = list(d.keys())
		values.append(list(d.values()))

	sql = """
	INSERT INTO misphot.bandes ({})
	VALUES
	%s
	RETURNING id
	""".format(','.join(keys))

	if debug: print(sql)
	result = execute_values(cursor, sql, values, fetch=True)
	bande_id = [id for (id,) in result]
	for (i, bande) in enumerate(vol.findall('bande')):
		insertCliches(bande, cursor, chantier_id, lot_id, vol_id, bande_id[i], sensors, srid)

	return bande_id


def insertVols(chantier, cursor, chantier_id, lot_id, srid):
	keys = []
	values = []
	for vol in chantier.findall('vol'):
		d = parseVol(vol)
		d['chantier'] = chantier_id
		keys = list(d.keys())
		values.append(list(d.values()))

	sql = """
	INSERT INTO misphot.vols ({})
	VALUES
	%s
	RETURNING id
	""".format(','.join(keys))

	if debug: print(sql)
	result = execute_values(cursor, sql, values, fetch=True)
	vol_id = [id for (id,) in result]

	for (i,vol) in enumerate(chantier.findall('vol')):
		sensors = insertSensors(vol, cursor, chantier_id, vol_id[i])
		insertBandes(vol, cursor, chantier_id, lot_id, vol_id[i], sensors, srid)
		insertTable('meteo',parseMeteo, vol, cursor, vol_id[i], 'vol', 'infosMto', 'obsMto')

	return vol_id


def insertLots(chantier, cursor, chantier_id):
	keys = []
	values = []
	for lot in chantier.findall('lot'):
		d = parseLot(lot)
		d['chantier'] = chantier_id
		keys = list(d.keys())
		values.append(list(d.values()))

	sql = """
	INSERT INTO misphot.lots ({})
	VALUES
	%s
	RETURNING id
	""".format(','.join(keys))

	if debug: print(sql)
	result = execute_values(cursor, sql, values, fetch=True)
	lot_id = [id for (id,) in result]


	for (i,lot) in enumerate(chantier.findall('lot')):
		insertTable('lot_channel', parseChannel, lot, cursor, lot_id[i], 'lot', 'rgbparams', 'parametres')
		insertTable('lot_bloc',    parseBloc, lot, cursor, lot_id[i], 'lot', 'ModeleBloc', 'ParamsModeleBloc')

	return lot_id


def insertChantier(root, cursor):
	srid,srid_ta,values = parseChantier(root)

	sql = "DELETE FROM misphot.chantiers where nom_generique='{}'".format(values['nom_generique'])

	if debug: print(sql)
	cursor.execute(sql)
	
	sql = """
	INSERT INTO misphot.chantiers ({})
	VALUES %s RETURNING id
	""".format(','.join(values.keys()))

	if debug: print(sql)
	result = execute_values(cursor, sql, [list(values.values())], fetch=True)
	chantier_id = result[0][0]

	chantier = find(root, 'chantier')
	if chantier is None:
		print('pas de chantier')
		return None


	lot_id = insertLots(chantier, cursor, chantier_id)
	insertVols(chantier, cursor, chantier_id, lot_id, srid)
	insertTable('ta_preparations', parsePrep, root, cursor, chantier_id, 'chantier', 'ta_preparation', 'ta_sequence', srid)
	insertTable('infos_mission',   parseInfo, root, cursor, chantier_id, 'chantier', 'info_chantier', 'info_mission')

	return chantier_id


try:
	connection = psycopg2.connect(
		user = user,
		password = password,
		host = host,
		port = port,
		database = database
	)
	cursor = connection.cursor()

	# cursor.execute(create_misphot.chantiers_table)
	# cursor.execute(create_misphot.vols_table)
	# cursor.execute(create_misphot.sensors_table)
	# cursor.execute(create_misphot.bandes_table)
	# cursor.execute(create_lots_table)
	# cursor.execute(create_misphot.cliches_table)
	# cursor.execute(create_indices)
	connection.commit()
 
	sorted_filename_no_archive = [f for f in sorted(glob.glob(filename)) if 'archive' not in f]

	for f in sorted_filename_no_archive:
		print(f,end='', flush=True)
		try:
			mydoc = ET.parse(f).getroot()
		except ET.ParseError as err:
			print(err, flush=True)
			continue

		chantier_id = insertChantier(mydoc, cursor)
		connection.commit()

		if chantier_id is None:
			continue

		print(' .',end='', flush=True)
		cursor.execute(refresh_timestamp_columns.format(chantier_id))
		connection.commit()

		print('.',end='', flush=True)
		cursor.execute(refresh_url_columns.format(chantier_id))
		connection.commit()

		print('.',end='', flush=True)
		cursor.execute(refresh_geometry_columns.format(chantier_id))
		connection.commit()

		print('.',end='', flush=True)
		cursor.execute(refresh_chantiers_columns.format(chantier_id))
		connection.commit()

		print(' ok', flush=True)

	

#except (Exception, psycopg2.Error) as error :
#	print('ERROR[' + filename +'] : '+ str(error))
finally:
	#closing database connection.
	if(connection):
		cursor.close()
		connection.close()

