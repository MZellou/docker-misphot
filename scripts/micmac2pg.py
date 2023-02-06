import sys
import psycopg2
from psycopg2.extras import execute_values
import xml.etree.ElementTree as ET
import glob
from os import path
from pyquaternion import Quaternion
import numpy
import re

filename = sys.argv[1] if len(sys.argv) > 1 else "*.xml"
srid     = sys.argv[2] if len(sys.argv) > 2 else 2154
user     = sys.argv[3] if len(sys.argv) > 3 else None
password = sys.argv[4] if len(sys.argv) > 4 else None
database = sys.argv[5] if len(sys.argv) > 5 else None
host     = sys.argv[6] if len(sys.argv) > 6 else None
port     = sys.argv[7] if len(sys.argv) > 7 else None
debug = False

def parseVector(node, name):
	node = node.find(name)
	return [float(text) for text in node.text.split()]


def parseIntrinsics(node, filename):
	fi = node.find('FileInterne')
	if fi is None:
		node = node.find('Interne')
	else:
		dirname = path.dirname(filename)
		filepath = fi.text if path.exists(fi.text) else path.join(dirname, fi.text)
		if not path.exists(filepath):
			filepath = path.join(dirname, path.basename(fi.text))
		node = ET.parse(filepath).getroot()
		
	node = node.find('CalibrationInternConique')
	KnownConv = node.find('KnownConv').text
	PP = parseVector(node, 'PP')
	F = node.find('F').text
	SzIm = parseVector(node, 'SzIm')
	
	node = node.find('CalibDistortion')
	ModRad = node.find('ModRad')
	CDist = parseVector(ModRad, 'CDist')
	CoeffDist = [float(n.text) for n in ModRad.findall('CoeffDist')] + [0,0,0]
	# CoeffDistInv = [float(n.text) for n in ModRad.findall('CoeffDistInv')] + [0,0,0]
	
	values = {
		'px': PP[0],
		'py': PP[1],
		'fx': F,
		'fy': F,
		'sx': SzIm[0],
		'sy': SzIm[1],
		'sk': 0,
		'cx': CDist[0],
		'cy': CDist[1],
		'c3': CoeffDist[0],
		'c5': CoeffDist[1],
		'c7': CoeffDist[2]
	}
	
	return values

def parseOrientation(root, filename, srid):
	OrientationConique = root.find('OrientationConique')
	if OrientationConique is None:
		print(' not a micmac Orientation ', end='')
		return None
	
	OrIntImaM2C = OrientationConique.find('OrIntImaM2C')
	values = parseIntrinsics(OrientationConique, filename)
	I00 = parseVector(OrIntImaM2C, 'I00')
	V10 = parseVector(OrIntImaM2C, 'V10')
	V01 = parseVector(OrIntImaM2C, 'V01')
	values['m00'] = V10[0]
	values['m10'] = V01[0]
	values['m20'] = I00[0]
	values['m01'] = V10[1]
	values['m11'] = V01[1]
	values['m21'] = I00[1]
	values['mask'] = 0
	
	Externe = OrientationConique.find('Externe')
	t = float(Externe.find('Time').text)
	if t > 0:
		t = t # convert to pg time with time zone
		values['t0'] = t
		values['t1'] = t
		values['te'] = t

	values['p'] = 'SRID={};POINTZ({})'.format(srid,Externe.find('Centre').text)
	
	ParamRotation = Externe.find('ParamRotation')
	CodageMatr = ParamRotation.find('CodageMatr')
	L1 = parseVector(CodageMatr, 'L1')
	L2 = parseVector(CodageMatr, 'L2')
	L3 = parseVector(CodageMatr, 'L3')
	
	matrix = numpy.array((L1,L2,L3))
	q = Quaternion(matrix=matrix)
	
	values['qw'] = q[0]
	values['qx'] = q[1]
	values['qy'] = q[2]
	values['qz'] = q[3]
	
	return values


def insertOrientation(root, filename, uri, srid, cursor):
	values = parseOrientation(root, filename, srid)
	
	if not values:
		return
		
	values['uri'] = uri

	sql = """
	INSERT INTO misphot.micmac_georefs_{} ({})
	VALUES %s
	""".format(srid, ','.join(values.keys()))

	if debug: print(sql)
	execute_values(cursor, sql, [list(values.values())])


try:
	connection = psycopg2.connect(
		user = user,
		password = password,
		host = host,
		port = port,
		database = database
	)
	cursor = connection.cursor()
	pattern = '((.*)/)?Orientation-(.*)\\....\\.xml'
	repl = '\\3'

	for f in sorted(glob.glob(filename)):
		print(f,end='', flush=True)
		try:
			root = ET.parse(f).getroot()
		except ET.ParseError as err:
			print(err, flush=True)
			continue

		uri = re.sub(pattern, repl, f)
		insertOrientation(root, f, uri, srid, cursor)
		
		print(' .',end='', flush=True)
		connection.commit()


		print(' ok', flush=True)

	

#except (Exception, psycopg2.Error) as error :
#	print('ERROR[' + filename +'] : '+ str(error))
finally:
	#closing database connection.
	if(connection):
		cursor.close()
		connection.close()

