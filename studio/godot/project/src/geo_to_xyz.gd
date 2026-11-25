extends Object
# geo_to_xyz.gd — math helper for converting (lat, lon) geographic coords
# into 3D Cartesian positions on a unit (or scaled) sphere, plus a
# great-circle slerp helper for drawing arc edges between two surface points.
#
# Conventions:
#   - lat_deg: -90..+90, +N
#   - lon_deg: -180..+180, +E
#   - y-axis = north pole
#   - x-axis = (lat=0, lon=0)   (prime meridian @ equator)
#   - z-axis = (lat=0, lon=+90) (East)
#
# Used by planet_map_controller.gd to place player nodes and to sample
# curved friend-edge polylines.

func lat_lon_to_xyz(lat_deg: float, lon_deg: float, radius: float) -> Vector3:
	var lat = deg_to_rad(lat_deg)
	var lon = deg_to_rad(lon_deg)
	var x = radius * cos(lat) * cos(lon)
	var y = radius * sin(lat)
	var z = radius * cos(lat) * sin(lon)
	return Vector3(x, y, z)


func great_circle_points(a: Vector3, b: Vector3, samples: int = 16) -> Array:
	# Sample `samples + 1` points along the shortest great-circle arc
	# between a and b. Both endpoints are assumed to lie on a sphere of
	# the same radius (we keep that radius). Slerp on Vector3 already
	# gives spherical interpolation; we just renormalize to defeat any
	# numerical drift away from the surface.
	var pts: Array = []
	var r := a.length()
	if r <= 0.0:
		return pts
	for i in range(samples + 1):
		var t = float(i) / float(samples)
		var p: Vector3 = a.slerp(b, t).normalized() * r
		pts.append(p)
	return pts


func great_circle_arc_lifted(a: Vector3, b: Vector3, samples: int = 16, lift: float = 0.06) -> Array:
	# Same as great_circle_points but lifts the mid-arc slightly above
	# the sphere so the edge mesh doesn't z-fight with the planet skin.
	# `lift` is a fraction of the sphere radius (0.06 = 6% bulge).
	var pts: Array = []
	var r := a.length()
	if r <= 0.0:
		return pts
	for i in range(samples + 1):
		var t = float(i) / float(samples)
		# Bell curve: 0 at endpoints, 1 at midpoint.
		var bulge = sin(t * PI)
		var p: Vector3 = a.slerp(b, t).normalized() * (r * (1.0 + lift * bulge))
		pts.append(p)
	return pts
