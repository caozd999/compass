#!/usr/bin/env python
'''
name: coastal_tools
authors: Steven Brus

last modified: 07/09/2018

'''
import numpy as np
import argparse
import pyflann
from skimage import measure
from  netCDF4 import Dataset
import matplotlib.pyplot as plt
import numpy as np
from scipy import spatial,io
import timeit
from mpl_toolkits.basemap import Basemap
import inject_bathymetry
import pprint
import mesh_definition_tools as mdt
plt.switch_backend('agg')

# Constants
km = 1000.0
deg2rad = np.pi/180.0
rad2deg = 180.0/np.pi

call_count = 0

######################################################################################
# Bounding box declarations (for coastal refinements)
######################################################################################

#---------------
# Region boxes
#---------------

# Bays and estuaries
Delaware_Bay =  {"include":[np.array([-75.61903,-74.22, 37.8, 40.312747])],
                 "exclude":[]}
Galveston_Bay = {"include":[np.array([-95.45,-94.4, 29, 30])],
                 "exclude":[]}

# Regions
Delaware_Region = {"include":[np.array([-77, -69.8 ,35.5, 41])],
                   "exclude":[]}

# Coastlines
US_East_Coast = {"include":[np.array([-81.7,-62.3,25.1,46.24])],
                 "exclude":[np.array([-66.0,-64.0,31.5,33.0]),    # Bermuda
                             np.array([-79.75,-70.0,20.0,28.5])]} # Bahamas
US_Gulf_Coast = {"include":[np.array([-98.0,-80.0,24.0,31.0]),     
                            np.array([-91.0,-86.0,20.0,22.0])     # Yucatan
                           ],   
                 "exclude":[]}

US_West_Coast = {"include":[np.array([-127.0,-116.0,32.5,49.0]),
                            np.array([-117.5,-109.0,23.0,32.5])   # Baja
                            ],
                 "exclude":[np.array([-116.5,-115.0,32.8,33.8]),  # Salton Sea
                            np.array([-120.5,-116.5,35.5,40.5])]} # Lake Tahoe, etc.
Alaska        = {"include":[np.array([-170.0,-141.0,49.0,72.0]),
                            np.array([-141.0,-129.5,49.0,61.0]),  # Southeast
                            np.array([-129.5,-121.0,49.0,55.0])   # Connects AK to CA
                           ],
                 "exclude":[]}

# Combined coastlines
CONUS = {"include":[],"exclude":[]}
CONUS["include"].extend(US_East_Coast["include"]) 
CONUS["include"].extend(US_Gulf_Coast["include"]) 
CONUS["include"].extend(US_West_Coast["include"])
CONUS["exclude"].extend(US_East_Coast["exclude"])
CONUS["exclude"].extend(US_West_Coast["exclude"])

Continental_US = {"include":[],"exclude":[]}
Continental_US["include"].extend(CONUS["include"])
Continental_US["include"].extend(Alaska["include"])
Continental_US["exclude"].extend(CONUS["exclude"])

#----------------
# Plotting boxes
#----------------

Western_Atlantic = np.array([-98.186645, -59.832744, 7.791301 ,45.942453])
Contiguous_US = np.array([-132.0,-59.832744,7.791301,51.0])
North_America = np.array([-175.0,-60.0,7.5,72.0])
Delaware = np.array([-77, -69.8 ,35.5, 41])
Entire_Globe = np.array([-180,180,-90,90])

#-----------------
# Restrict Boxes
#-----------------

Delaware_restrict = {"include":[np.array([[-75.853,39.732],
                                          [-74.939,36.678],
                                          [-71.519,40.156],
                                          [-75.153,40.077]]),
                                np.array([[-76.024,37.188],
                                          [-75.214,36.756],
                                          [-74.512,37.925],
                                          [-75.274,38.318]])],
                     "exclude":[]}

######################################################################################
# User-defined inputs
######################################################################################

default_params = {

# Path to bathymetry data and name of file
"nc_file": "./earth_relief_15s.nc",

# Bounding box of coastal refinement region
"region_box": Continental_US,
"origin": np.array([-100,40]),
"restrict_box": None,

# Coastline extraction parameters
"z_contour": 0.0,
"n_longest": 10,

# Global mesh parameters
"grd_box": Entire_Globe ,
"ddeg": .1,
"mesh_type": 'EC',     #'EC' (defaults to 60to30), 'QU' (uses dx_max_global), 'RRS' (uses dx_max_global and dx_min_global)
"dx_max_global": 30.0*km,
"dx_min_global": 10.0*km,

# Coastal mesh parameters
"dx_min_coastal": 10.0*km,
"trans_width": 600.0*km,
"trans_start": 400.0*km,

# Bounding box of plotting region
"plot_box": North_America,

# Options
"nn_search": "flann",
"plot_option": True

}

######################################################################################
# Functions
######################################################################################

def coastal_refined_mesh(params,cell_width=None,lon_grd=None,lat_grd=None): #{{{
  
  coastal_refined_mesh.counter += 1
  call_count = coastal_refined_mesh.counter

  if cell_width is None:
    # Create the background cell width array 
    lon_grd,lat_grd,cell_width = create_background_mesh(params["grd_box"],params["ddeg"],params["mesh_type"],params["dx_min_global"],params["dx_max_global"],
                                                        params["plot_option"],params["plot_box"],call_count)
 
  # Get coastlines from bathy/topo  data set   
  coastlines = extract_coastlines(params["nc_file"],params["region_box"],params["z_contour"],params["n_longest"],
                                  params["plot_option"],params["plot_box"],call_count)
  
  # Compute distance from background grid points to coastline 
  D = distance_to_coast(coastlines,lon_grd,lat_grd,params["origin"],params["nn_search"],
                        params["plot_option"],params["plot_box"],call_count)
  
  # Blend coastline and background resolution, save cell_width array as .mat file  
  cell_width = compute_cell_width(D,cell_width,lon_grd,lat_grd,params["dx_min_coastal"],params["trans_start"],params["trans_width"],params["restrict_box"],
                                  params["plot_option"],params["plot_box"],lon_grd,lat_grd,coastlines,call_count)

  # Save matfile
  #save_matfile(cell_width/km,lon_grd,lat_grd)

  return (cell_width,lon_grd,lat_grd) 
  #}}}
coastal_refined_mesh.counter = 0

##############################################################

def create_background_mesh(grd_box,ddeg,mesh_type,dx_min,dx_max,  #{{{
                           plot_option=False,plot_box=[],call=None): 

  # Create cell width background grid
  lat_grd = np.arange(grd_box[2],grd_box[3],ddeg)
  lon_grd = np.arange(grd_box[0],grd_box[1],ddeg)
  nx_grd = lon_grd.size
  ny_grd = lat_grd.size
  print "Background grid dimensions:", ny_grd,nx_grd
  
  # Assign background grid cell width values
  if mesh_type == 'QU':
    cell_width_lat = dx_max/km*np.ones(lat_grd.size)
  elif mesh_type == 'EC':
    cell_width_lat = mdt.EC_CellWidthVsLat(lat_grd)
  elif mesh_type == 'RRS':
    cell_width_lat = mdt.RRS_CellWidthVsLat(lat_grd,dx_max/km,dx_min/km)  
  cell_width = np.tile(cell_width_lat,(nx_grd,1)).T*km

  # Plot background cell width
  if plot_option:

    plt.figure()
    plt.plot(lat_grd,cell_width_lat)
    plt.savefig('bckgrnd_grid_cell_width_vs_lat'+str(call)+'.png')

    plt.figure()
    plt.contourf(lon_grd,lat_grd,cell_width)
    plot_coarse_coast(plot_box)
    plt.colorbar()
    plt.savefig('bckgnd_grid_cell_width'+str(call)+'.png',bbox_inches='tight')

  return (lon_grd,lat_grd,cell_width) #}}}

##############################################################

def extract_coastlines(nc_file,region_box,z_contour=0,n_longest=10, #{{{
                       plot_option=False,plot_box=[],call=None): 

  # Open NetCDF file and read cooordintes
  nc_fid = Dataset(nc_file,"r")
  lon = nc_fid.variables['lon'][:]
  lat = nc_fid.variables['lat'][:]
  zdata = nc_fid.variables['z']
  
  # Get coastlines for refined region
  coastline_list = []
  for box in region_box["include"]:

    # Find coordinates and data inside bounding box
    lon_region,lat_region,z_region = get_data_inside_box(lon,lat,zdata,box)
    print "Regional bathymetry data shape:", z_region.shape
    
    # Find coastline contours
    print "Extracting coastline"
    contours = measure.find_contours(z_region,z_contour)

    # Keep only n_longest coastlines and those not within exclude areas
    contours.sort(key=len,reverse=True)
    for c in contours[:n_longest]:
      # Convert from pixel to lon,lat
      c[:,0] = (box[3]-box[2])/float(len(lat_region))*c[:,0] + box[2]        
      c[:,1] = (box[1]-box[0])/float(len(lon_region))*c[:,1] + box[0]
      c = np.fliplr(c)
  
      exclude = False
      for area in region_box["exclude"]:
        # Determine coastline coordinates in exclude area
        x_idx = np.where((c[:,0] > area[0]) & (c[:,0] < area[1]))
        y_idx = np.where((c[:,1] > area[2]) & (c[:,1] < area[3]))
        idx = np.intersect1d(x_idx,y_idx)
  
        # Exlude coastlines that are entirely contained in exclude area
        if idx.size == c.shape[0]:
          exclude = True
          break
  
      # Keep coastlines not entirely contained in exclude areas
      if not exclude:
        cpad= np.vstack((c,[np.nan,np.nan]))
        coastline_list.append(cpad)

    print "Done"
  
  # Combine coastlines 
  coastlines = np.concatenate(coastline_list)
  
  if plot_option:
  
    # Find coordinates and data inside plotting box
    lon_plot,lat_plot,z_plot = get_data_inside_box(lon,lat,zdata,plot_box)
 
    # Plot bathymetry data, coastlines and region boxes
    plt.figure()
    levels = np.linspace(np.amin(z_plot),np.amax(z_plot),100)
    ds = 10                              # Downsample
    dsx = np.arange(0,lon_plot.size,ds)  # bathy data
    dsy = np.arange(0,lat_plot.size,ds)  # to speed up
    dsxy = np.ix_(dsy,dsx)               # plotting
    plt.contourf(lon_plot[dsx],lat_plot[dsy],z_plot[dsxy],levels=levels)
    plot_coarse_coast(plot_box)
    plt.plot(coastlines[:,0],coastlines[:,1],color='white')
    for box in region_box["include"]:
      plot_region_box(box,'b')
    for box in region_box["exclude"]:
      plot_region_box(box,'r')
    plt.colorbar()
    plt.axis('equal')
    plt.savefig('bathy_coastlines'+str(call)+'.png',bbox_inches='tight')

  return coastlines #}}}

##############################################################

def distance_to_coast(coastlines,lon_grd,lat_grd,origin,nn_search, #{{{
                      plot_option=False,plot_box=[],call=None):

  # Convert to x,y and create kd-tree
  coast_pts = coastlines[np.isfinite(coastlines).all(axis=1)]
  coast_pts_xy = np.copy(coast_pts)
  coast_pts_xy[:,0],coast_pts_xy[:,1] = CPP_projection(coast_pts[:,0],coast_pts[:,1],origin)
  if nn_search == "kdtree":
    tree = spatial.KDTree(coast_pts_xy)
  elif nn_search == "flann":
    flann = pyflann.FLANN()
    flann.build_index(coast_pts_xy,algorithm='kdtree',target_precision=1.0)
  
  # Put x,y backgound grid coordinates in a nx_grd x 2 array for kd-tree query
  Lon_grd,Lat_grd = np.meshgrid(lon_grd,lat_grd)
  X_grd,Y_grd = CPP_projection(Lon_grd,Lat_grd,origin)
  pts = np.vstack([X_grd.ravel(), Y_grd.ravel()]).T
  
  # Find distances of background grid coordinates to the coast
  print "Finding distance"
  start = timeit.default_timer()
  if nn_search == "kdtree":
    d,idx = tree.query(pts)
  elif nn_search == "flann":
    idx,d = flann.nn_index(pts,checks=700)
    d = np.sqrt(d)
  end = timeit.default_timer()
  print "Done"
  print end-start, " seconds"
  
  # Make distance array that corresponds with cell_width array
  D = np.reshape(d,Lon_grd.shape)
  
  if plot_option:

    # Find coordinates and data inside plotting box
    lon_plot,lat_plot,D_plot = get_data_inside_box(lon_grd,lat_grd,D,plot_box)
 
    # Plot distance to coast
    plt.figure()
    D_plot = D_plot/km 
    levels = np.linspace(np.amin(D_plot),np.amax(D_plot),10)
    plt.contourf(lon_plot,lat_plot,D_plot,levels=levels)
    plot_coarse_coast(plot_box)
    plt.plot(coastlines[:,0],coastlines[:,1],color='white')
    plt.grid(xdata=lon_plot,ydata=lat_plot,c='k',ls='-',lw=0.1,alpha=0.5)
    plt.colorbar()
    plt.axis('equal')
    plt.savefig('distance'+str(call)+'.png',bbox_inches='tight')

  return D #}}}

##############################################################

def compute_cell_width(D,cell_width,lon,lat,dx_min,trans_start,trans_width,restrict_box, #{{{
                       plot_option=False,plot_box=[],lon_grd=[],lat_grd=[],coastlines=[],call=None):


  # Compute cell width based on distance
  backgnd_weight = .5*(np.tanh((D-trans_start-.5*trans_width)/(.2*trans_width))+1)
  dist_weight = 1-backgnd_weight
  ## Use later for depth and slope dependent resolution
  ##hres = np.maximum(dx_min*bathy_grd/20,dx_min)
  ##hres = np.minimum(hres,dx_max)
  #hw = np.zeros(Lon_grd.shape) + dx_max
  #hw[ocn_idx] = np.sqrt(9.81*bathy_grd[ocn_idx])*12.42*3600/25
  #hs = .20*1/dbathy_grd
  #h = np.fmin(hs,hw)
  #h = np.fmin(h,dx_max)
  #h = np.fmax(dx_min,h)

  if restrict_box:
    for box in restrict_box["include"]:
      idx = get_indices_inside_quad(lon,lat,box)
      cell_width[idx] = (dx_min*dist_weight[idx]+np.multiply(cell_width[idx],backgnd_weight[idx]))
  else:
    cell_width = (dx_min*dist_weight+np.multiply(cell_width,backgnd_weight))
    
  if plot_option:

    # Find coordinates and data inside plotting box
    lon_plot,lat_plot,cell_width_plot = get_data_inside_box(lon_grd,lat_grd,cell_width/km,plot_box)

    # Plot cell width
    plt.figure()
    levels = np.linspace(np.amin(cell_width_plot),np.amax(cell_width_plot),100)
    plt.contourf(lon_plot,lat_plot,cell_width_plot,levels=levels)
    plot_coarse_coast(plot_box)
    plt.plot(coastlines[:,0],coastlines[:,1],color='white')
    if restrict_box:
      for box in restrict_box["include"]:
        plt.plot([box[0,0],box[1,0]],[box[0,1],box[1,1]],'b-')
        plt.plot([box[1,0],box[2,0]],[box[1,1],box[2,1]],'b-')
        plt.plot([box[2,0],box[3,0]],[box[2,1],box[3,1]],'b-')
        plt.plot([box[3,0],box[0,0]],[box[3,1],box[0,1]],'b-')
    plt.colorbar()
    plt.axis('equal')
    plt.savefig('cell_width'+str(call)+'.png',bbox_inches='tight')

  return cell_width #}}}

##############################################################

def save_matfile(cell_width,lon,lat):

  io.savemat('cellWidthVsLatLon.mat',mdict={'cellWidth':cell_width,'lon':lon,'lat':lat})

##############################################################

def CPP_projection(lon,lat,origin):

  R = 6378206.4
  origin = origin*deg2rad
  x = R*(lon*deg2rad-origin[0])*np.cos(origin[1])
  y = R*lat*deg2rad

  return x,y

##############################################################

def get_data_inside_box(lon,lat,data,box,idx=False):

  # Find indicies of coordinates inside bounding box
  lon_idx, = np.where((lon >= box[0]) & (lon <= box[1]))
  lat_idx, = np.where((lat >= box[2]) & (lat <= box[3]))
  
  # Get indicies inside bounding box
  lon_region = lon[lon_idx]
  lat_region = lat[lat_idx]
  latlon_idx = np.ix_(lat_idx,lon_idx)

  # Return data inside bounding box
  if idx == False:

    try:     # Numpy indexing
      z_region = data[latlon_idx]
    except:  # NetCDF indexing
      z_region = data[lat_idx,lon_idx]

    return (lon_region,lat_region,z_region)

  # Return indicies of data inside bounding box
  elif idx == True:

    return latlon_idx

##############################################################

def get_indices_inside_quad(lon,lat,box):
  
  # Create vectors of all coordinates
  Lon_grd,Lat_grd = np.meshgrid(lon,lat)
  X = Lon_grd.ravel()
  Y = Lat_grd.ravel()

  # Find indices of coordinates in convex hull of quad region
  xb1 = np.amin(box[:,0])
  xb2 = np.amax(box[:,0])
  yb1 = np.amin(box[:,1])
  yb2 = np.amax(box[:,1])
  idxx = np.where((X >= xb1) & (X <= xb2))  
  idxy = np.where((Y >= yb1) & (Y <= yb2))
  idx_ch = np.intersect1d(idxx,idxy)
  idx = np.copy(idx_ch)

  # Initialize the local coordinate vectors to be outside unit square
  R = 0.0*X - 10.0
  S = 0.0*Y - 10.0

  # Initialize the coordinate vectors for points inside convex hull of quad region
  r = 0.0*R[idx]
  s = 0.0*S[idx]
  x = X[idx]
  y = Y[idx]

  # Map all coordinates in convex hull of quad region to unit square 
  #   by solving inverse transformaion with Newton's method
  tol = 1e-8
  maxit = 25 
  for it in range(0,maxit):

      # Compute shape fuctions
      phi1 = np.multiply((1.0-r),(1.0-s))
      phi2 = np.multiply((1.0+r),(1.0-s))
      phi3 = np.multiply((1.0+r),(1.0+s))
      phi4 = np.multiply((1.0-r),(1.0+s))
  
      # Compute functions that are being solved
      f1 = .25*(phi1*box[0,0] + phi2*box[1,0] + phi3*box[2,0] + phi4*box[3,0]) - x
      f2 = .25*(phi1*box[0,1] + phi2*box[1,1] + phi3*box[2,1] + phi4*box[3,1]) - y
  
      # Compute Jacobian 
      df1ds = .25*((r-1.0)*box[0,0] - (1.0+r)*box[1,0] + (1.0+r)*box[2,0] + (1.0-r)*box[3,0])
      df1dr = .25*((s-1.0)*box[0,0] + (1.0-s)*box[1,0] + (1.0+s)*box[2,0] - (1.0+s)*box[3,0])
      df2ds = .25*((r-1.0)*box[0,1] - (1.0+r)*box[1,1] + (1.0+r)*box[2,1] + (1.0-r)*box[3,1])
      df2dr = .25*((s-1.0)*box[0,1] + (1.0-s)*box[1,1] + (1.0+s)*box[2,1] - (1.0+s)*box[3,1])
  
      # Inverse of 2x2 matrix 
      det_recip = np.multiply(df1dr,df2ds) - np.multiply(df2dr,df1ds)    
      det_recip = 1.0/det_recip
      dr = np.multiply(det_recip, np.multiply(df2ds,f1)-np.multiply(df1ds,f2))
      ds = np.multiply(det_recip,-np.multiply(df2dr,f1)+np.multiply(df1dr,f2))
  
      # Apply Newton's method
      rnew = r - dr
      snew = s - ds 
  
      # Find converged values
      err = R[idx] - rnew
      idxr = np.where(np.absolute(err) < tol)
      err = S[idx] - snew
      idxs = np.where(np.absolute(err) < tol)
      idx_conv = np.intersect1d(idxr,idxs)
  
      # Update solution 
      R[idx] = rnew
      S[idx] = snew
  
      # Find indicies of unconverged values
      idx = np.delete(idx,idx_conv)
      print "Iteration: ", it, "unconverged values: ",idx.size
  
      # Terminate once all values are converged    
      if idx.size == 0:
        break 
  
      # Initialize to unconverged values for next iteration
      r = R[idx]
      s = S[idx]
      x = X[idx]
      y = Y[idx]
   

  # Find any remaining unconverged values
  idx_nc = np.unravel_index(idx,Lon_grd.shape)

  # Find indicies of coordinates inside quad region
  lon_idx, = np.where((R >= -1.0) & (R <= 1.0))
  lat_idx, = np.where((S >= -1.0) & (S <= 1.0))
  idx = np.intersect1d(lon_idx,lat_idx)
  idx = np.unravel_index(idx,Lon_grd.shape)
  
  # Plot values inside quad region
  plt.figure()
  plt.plot(X,Y,'.')
  plt.plot(Lon_grd[idx],Lat_grd[idx],'.')
  plt.plot(Lon_grd[idx_nc],Lat_grd[idx_nc],'.')
  plt.plot(box[:,0],box[:,1],'o')
  plt.savefig("restrict_box.png")

  return idx
  
##############################################################

def plot_coarse_coast(plot_box):

  m = Basemap(projection='cyl',llcrnrlat=plot_box[2],urcrnrlat=plot_box[3],\
              llcrnrlon=plot_box[0],urcrnrlon=plot_box[1],resolution='l')
  m.drawcoastlines()

##############################################################

def plot_region_box(box,color):
  ls = color+'-'
  plt.plot([box[0],box[1]],[box[2],box[2]],ls)
  plt.plot([box[1],box[1]],[box[2],box[3]],ls)
  plt.plot([box[1],box[0]],[box[3],box[3]],ls)
  plt.plot([box[0],box[0]],[box[3],box[2]],ls)


######################################################################################
#  Incorporate later for depth and slope dependent resolution
######################################################################################


## 
## Interpolate bathymetry onto background grid
#Lon_grd = Lon_grd*deg2rad
#Lat_grd = Lat_grd*deg2rad
#bathy = inject_bathymetry.interpolate_bathymetry(data_path+nc_file,Lon_grd.ravel(),Lat_grd.ravel())
#bathy_grd = -1.0*np.reshape(bathy,(ny_grd,nx_grd))
#ocn_idx = np.where(bathy_grd > 0)
#
#if plot_option:
#  plt.figure()
#  levels = np.linspace(0,11000,100)
#  plt.contourf(lon_grd,lat_grd,bathy_grd,levels=levels)
#  plot_coarse_coast(plot_box)
#  plt.colorbar()
#  plt.axis('equal')
#  plt.savefig('bckgnd_grid_bathy.png',bbox_inches='tight')

## Interpolate bathymetry gradient onto background grid
#dbathy = inject_bathymetry.interpolate_bathymetry(data_path+nc_file,Lon_grd.ravel(),Lat_grd.ravel(),grad=True)
#dbathy = np.reshape(dbathy,(ny_grd,nx_grd))
#dbathy_grd = np.zeros((ny_grd,nx_grd))
#dbathy_grd[ocn_idx] = dbathy[ocn_idx]
#
#if plot_option:
#  plt.figure()
#  plt.contourf(lon_grd,lat_grd,1/dbathy_grd)
#  plot_coarse_coast(plot_box)
#  plt.colorbar()
#  plt.axis('equal')
#  plt.savefig('bckgnd_grid_bathy_grad.png',bbox_inches='tight')