## Copyright 2021 Morten Hartvig Hansen
#
# This file is part of CASEToolBox/CASEDamp.

# CASEToolBox/CASEDamp is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# CASEToolBox/CASEDamp is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with CASEToolBox/CASEDamp.  If not, see <https://www.gnu.org/licenses/>.
#
#
import os
import numpy as np
from scipy import interpolate
from matplotlib import pyplot as plt
from . import casedamp_precompiled_functions as cpf
## Class that provides the interpolation functions for the CL and CD curves
class curve_interpolate:
    def __init__(self,itype,aoa,cl):
        self.itype=itype
        if itype == 'pchip':
            self.fcn = interpolate.PchipInterpolator(aoa,cl)
            self.der = interpolate.PchipInterpolator(aoa,cl).derivative()
        elif itype == 'akima':
            self.fcn = interpolate.Akima1DInterpolator(aoa,cl)
            self.der = interpolate.Akima1DInterpolator(aoa,cl).derivative()
        else: # linear is default
            self.fcn = interpolate.interp1d(aoa,cl,axis=0)
            yp = np.zeros(np.shape(cl))
            for icol in range(np.size(cl,axis=1)):
                yp[1:,icol] = np.diff(cl[:,icol])/np.diff(aoa)
            yp[0,:] = yp[1,:]
            self.der = interpolate.interp1d(aoa,yp,kind='next',axis=0)
## Class that contains the input and results for each airfoil
class airfoil_class:
    def __init__(self,data,thickness):
        self.data = data
        self.thickness = thickness
        self.fcn=None
## Class for reading airfoil polars from HAWC2 model
class read_HAWC2_pc_file:
    def __init__(self,fn,itype):
        fd=open(fn,'r')
        txt=fd.read()
        lines=txt.split("\n")
        iline=0
        nset=int(lines[iline].split()[0])
        self.fn = os.path.basename(fn)
        self.set = {}
        self.nset = nset
        for iset in range(nset):
            iline+=1
            nairfoil = int(lines[iline].split()[0])
            airfoil = {}
            for iairfoil in range(nairfoil):
                iline+=1
                airfoil_nr, nrows = map(int, lines[iline].split()[:2])
                thickness = float(lines[iline].split()[2])
                data = np.array([lines[iline+i+1].split() for i in range(nrows)], dtype=float)
                airfoil[iairfoil] = airfoil_class(data,thickness)
                iline+=nrows
                airfoil[iairfoil].fcn = curve_interpolate(itype,data[:,0],data[:,1:3])
            self.set[iset] = airfoil
## Class for reading airfoil polars from Flex model
class read_Flex_pro_file:
    def __init__(self,fn,itype):
        # Read airfoil polars and interpolate them to equidistant arrays
        fd=open(fn,'r')
        txt=fd.read()
        lines=txt.split("\n")
        iline=4
        nset = 1 # There is only one set in a Flex pro-file
        self.fn = os.path.basename(fn)
        self.set = {}
        self.nset = nset
        nairfoil = int(lines[1].split()[0])
        thicknesses = np.array(lines[2].split(), dtype=np.float)
        nrows = int(lines[3].split()[0])
        airfoil = {}
        for iairfoil in range(nairfoil):
            iline+=1
            data = np.array([lines[iline+i].split() for i in range(nrows)], dtype=np.float)
            airfoil[iairfoil] = airfoil_class(data,thicknesses[iairfoil])
            iline+=nrows
            airfoil[iairfoil].fcn = curve_interpolate(itype,data[:,0],data[:,1:3])
        self.set[0] = airfoil
## Class for the analysis and design of polars
class aero_damp_analyzer:
    def __init__(self,airfoil,fn,itype,aoas,psis,beta,gama,phi,k):
        # Remember filename
        self.fn = os.path.basename(fn)
        # Original CL and CD curves from polar file
        aoa = airfoil.data[:,0]
        cl  = airfoil.data[:,1]
        cd  = airfoil.data[:,2]
        # Copy airfoil for update of splines and damping computations (may not be needed because all computations are done on edited curves)
        self.airfoil = airfoil
        self.itype = itype
        # Remember the curves
        self.user_aoas    = aoa
        self.cls     = cl.copy()
        self.cls_new = cl.copy()
        self.cds     = cd.copy()
        self.cds_new = cd.copy()
        # Compute scaling factor for distance calculations
        self.aoascale = 1.0/(np.max(aoa) - np.min(aoa))
        self.clscale = 1.0/(np.max(cl) - np.min(cl))
        self.cdscale = 1.0/(np.max(cd) - np.min(cd))
        # Selected point and flags
        self.ipoint_selected = []
        self.ipoint_on_CL = True
        self.a_point_selected = False
        # Small and large increments for curve editing
        self.dc1 = 0.001
        self.dc2 = 0.01
        # Max distance for point picking
        self.maxd = 0.05
        # Interpolated CL and CD curves for damping computations
        self.aoas = aoas
        self.naoas = aoas.shape[0]
        self.clcd_clpcdp = np.zeros((self.naoas,4))
        self.update_interpolated_values()
        self.polar_changed = True
        # Directions of vibrations
        self.psis = psis
        self.npsis = psis.shape[0]
        # Mesh grid for contour
        [self.psi_grid,self.aoa_grid]=np.meshgrid(self.psis,self.aoas)
        # Allocate the 2D-arrays for the four damping terms
        self.W_tran1 = np.zeros((self.naoas,self.npsis))
        self.W_tran2 = np.zeros((self.naoas,self.npsis))
        self.W_tors1 = np.zeros((self.naoas,self.npsis))
        self.W_tors2 = np.zeros((self.naoas,self.npsis))
        self.eta = np.zeros((self.naoas,self.npsis))
        # Levels
        self.N1 = 0
        self.N2 = 0
        # Free parameters
        self.beta = beta
        self.gama = np.radians(gama)
        self.phi  = np.radians(phi)
        self.k    = k
        self.ured = 1.0/k
        # Compute damping terms
        self.compute_damping_terms()
        self.polar_changed = False
        self.compute_damping_eta()
        # Create figure
        self.fig, self.ax = plt.subplots(2,1,figsize=[10,12],gridspec_kw={'height_ratios':[1,2]})
        # Add title
        self.ax[0].set_title('Airfoil with relative thickness of {:.1f}% in file ''{:s}'''.format(airfoil.thickness,self.fn),size=10)
        # Plot original CL and CD curves and their edited curves
        self.clcurve,        = self.ax[0].plot(aoa,cl,'.-',color='lightblue')  
        self.cdcurve,        = self.ax[0].plot(aoa,cd,'.-',color='lightgreen')  
        self.new_clcurve,    = self.ax[0].plot(aoa,cl,'.',color='blue',  picker=True, pickradius=5)  
        self.new_cdcurve,    = self.ax[0].plot(aoa,cd,'.',color='green', picker=True, pickradius=5)  
        self.int_clcurve,    = self.ax[0].plot(self.aoas,self.clcd_clpcdp[:,0],'-',color='blue')  
        self.int_cdcurve,    = self.ax[0].plot(self.aoas,self.clcd_clpcdp[:,1],'-',color='green')  
        # Initiate plot of selected point
        self.selected_point, = self.ax[0].plot([],[],'ro')
        self.ax[0].grid(True)
        # Contour levels of damping coefficient
        self.N1=np.int64(-np.floor(np.min(self.eta)))
        self.N2=np.int64( np.floor(np.max(self.eta))+1)
        n1=np.int64(np.max([0,-np.floor(np.min(self.eta))]))
        n2=np.int64(           np.floor(np.max(self.eta))+1)
        self.l=np.arange(-self.N1,self.N2+1)
        # Color codes for levels
        f1=np.linspace(1.0/self.N1,n1/self.N1,n1)
        f2=np.linspace(1.0/self.N2,(n2+1)/self.N2,n2+1)
        self.m=np.zeros((n1+n2+1,3))
        m0=np.array([1.0,1.0,1.0])
        m1=np.array([1.0,0.0,0.0])
        m2=np.array([0.0,1.0,0.0])
        for i in range(n1):
            self.m[i,:]=m1*f1[n1-i-1]+m0*(1.0-f1[n1-i-1])
        for i in range(n2+1):
            self.m[n1+i,:]=m2*f2[i]+m0*(1.0-f2[i])
        # Make plot
        self.damp_contour = self.ax[1].contourf(self.aoa_grid,self.psi_grid,self.eta,levels=self.l,colors=self.m)
        self.ax[1].grid(True)
        self.ax[1].set_xlabel('Angle of attack [deg]')
        self.ax[1].set_ylabel('Dir. of vib. relative to chord [deg]')
        self.contour_title = 'Parameters: beta (b/B) = {:.2f}, gamma (t/T) = {:.1f} deg/c, phi (f/F) =  {:.0f} deg, k (k/K) = {:.2f}'
        self.ax[1].set_title(self.contour_title.format(self.beta,np.degrees(self.gama),np.degrees(self.phi),1.0/self.ured),size=10)
        # Adjust positions of plots
        self.fig.subplots_adjust(bottom=0.05, right=0.85, top=0.95)
        # Add color bar
        cax = plt.axes([0.9, 0.05, 0.05, 0.9])
        self.fig.colorbar(self.damp_contour,cax=cax)
        # Remove keyboard shortcuts that are used for other stuff here
        plt.rcParams['keymap.fullscreen'].remove('f')
        plt.rcParams['keymap.save'].remove('s')
        plt.rcParams['keymap.xscale'].remove('k')
        # Mouse events
        self.fig.canvas.mpl_connect('pick_event', self.onpick)
        self.fig.canvas.mpl_connect('key_press_event',self.key_input)


    # Functions that updates the interpolations and their evaluations
    def update_interpolated_values(self):
        cl = curve_interpolate(self.itype,self.user_aoas,self.cls_new)
        cd = curve_interpolate(self.itype,self.user_aoas,self.cds_new)
        self.clcd_clpcdp[:,0] = cl.fcn(self.aoas)
        self.clcd_clpcdp[:,1] = cd.fcn(self.aoas)
        self.clcd_clpcdp[:,2] = cl.der(self.aoas)*180.0/np.pi
        self.clcd_clpcdp[:,3] = cd.der(self.aoas)*180.0/np.pi

    # Function for computing the damping coefficients
    def compute_damping_terms(self):
        self.W_tran1,self.W_tran2,self.W_tors1,self.W_tors2 = cpf.compute_damping_terms(self.aoas,self.psis,self.clcd_clpcdp)

    # Function for computing the damping coefficients
    def compute_damping_eta(self):
        self.eta = self.W_tran1 + self.beta**2*self.W_tran2 + self.ured*self.gama*np.sin(self.phi)*self.W_tors1 + self.ured*self.gama*self.beta*np.cos(self.phi)*self.W_tors2


    # Function for the pick event on the CL and CD curves
    def onpick(self,event):
        if event.artist != self.new_clcurve and event.artist != self.new_cdcurve:
            return True
        if len(event.ind) == 0:
            return True
        # Which curve?
        self.ipoint_on_CL = event.artist == self.new_clcurve
        # Select or unselect point
        if event.ind[0] in self.ipoint_selected and self.a_point_selected:
            self.ipoint_selected = []
            self.a_point_selected = False
        else:
            self.ipoint_selected = [event.ind[0]]
            self.a_point_selected = True
        # Update plot for the highlight
        self.update_plot()
        return True

    # Function that handles the keyboard inputs
    def key_input(self,event):
        # Modify the CL and CD curves at the selected point
        if self.a_point_selected:
            if event.key == 'up':
                if self.ipoint_on_CL:
                    self.cls_new[self.ipoint_selected[0]] += self.dc1
                else:
                    self.cds_new[self.ipoint_selected[0]] += self.dc1
            if event.key == 'shift+up':
                if self.ipoint_on_CL:
                    self.cls_new[self.ipoint_selected[0]] += self.dc2
                else:
                    self.cds_new[self.ipoint_selected[0]] += self.dc2
            if event.key == 'down':
                if self.ipoint_on_CL:
                    self.cls_new[self.ipoint_selected[0]] -= self.dc1
                else:
                    self.cds_new[self.ipoint_selected[0]] -= self.dc1
            if event.key == 'shift+down':
                if self.ipoint_on_CL:
                    self.cls_new[self.ipoint_selected[0]] -= self.dc2
                else:
                    self.cds_new[self.ipoint_selected[0]] -= self.dc2
            self.update_interpolated_values()
            self.polar_changed = True
            self.update_plot()
        # Update the damping contour plot
        if event.key == 'u':
            if self.polar_changed:
                self.compute_damping_terms()
                self.polar_changed = False
            self.compute_damping_eta()
            self.update_damping_plot()
        # Modify the 'beta' value
        if event.key == 'b':
            self.beta -= 0.01 
            self.update_parameters_in_title()
        if event.key == 'B':
            self.beta += 0.01 
            self.update_parameters_in_title()
        # Modify the 'gama' value
        if event.key == 't':
            self.gama -= np.radians(0.1)  
            self.update_parameters_in_title()
        if event.key == 'T':
            self.gama += np.radians(0.1) 
            self.update_parameters_in_title()
        # Modify the 'phi' value
        if event.key == 'f':
            self.phi -= np.radians(15.0) 
            self.update_parameters_in_title()
        if event.key == 'F':
            self.phi += np.radians(15.0)
            self.update_parameters_in_title()
        # Modify the 'ured' value
        if event.key == 'k':
            self.k -= 0.01 
            self.ured = 1.0/self.k
            self.update_parameters_in_title()
        if event.key == 'K':
            self.k += 0.01 
            self.ured = 1.0/self.k
            self.update_parameters_in_title()
        if event.key == 's':
            self.fig.savefig('QSdamp_' + os.path.splitext(self.fn)[0] + '.png',dpi = 300)
        if event.key == 'shift+s':
            self.airfoil.data[:,1] = self.cls_new
            self.airfoil.data[:,2] = self.cds_new

    # Function that updates the title with parameters
    def update_parameters_in_title(self):
        self.ax[1].set_title(self.contour_title.format(self.beta,np.degrees(self.gama),np.degrees(self.phi),1.0/self.ured),size=10)
        self.selected_point.figure.canvas.draw()

    # Function that replots the CL and CD curves
    def update_plot(self):
        self.clcurve.set_data(self.user_aoas, self.cls)
        self.cdcurve.set_data(self.user_aoas, self.cds)
        self.new_clcurve.set_data(self.user_aoas, self.cls_new)
        self.new_cdcurve.set_data(self.user_aoas, self.cds_new)
        self.int_clcurve.set_data(self.aoas,self.clcd_clpcdp[:,0])  
        self.int_cdcurve.set_data(self.aoas,self.clcd_clpcdp[:,1])  
        if len(self.ipoint_selected) > 0:
            for i in self.ipoint_selected:
                if self.ipoint_on_CL:
                    self.selected_point.set_data(self.user_aoas[i], self.cls_new[i])
                else:
                    self.selected_point.set_data(self.user_aoas[i], self.cds_new[i])
        else:
            self.selected_point.set_data([], [])
        self.clcurve.figure.canvas.draw()
        self.cdcurve.figure.canvas.draw()
        self.new_clcurve.figure.canvas.draw()
        self.new_cdcurve.figure.canvas.draw()
        self.int_clcurve.figure.canvas.draw()
        self.int_cdcurve.figure.canvas.draw()
        self.selected_point.figure.canvas.draw()
    # Function that replots the damping contour plot
    def update_damping_plot(self):
        self.ax[1].contourf(self.aoa_grid,self.psi_grid,self.eta,levels=self.l,colors=self.m)

# Main function of the package
def casedamp(fn,itype,iset,iairfoil,aoas,psis,beta=0.0,gama=0.0,phi=0.0,k=0.1):
        try:
            pc = read_HAWC2_pc_file(fn,itype)
        except:
            try:
                pc = read_Flex_pro_file(fn,itype)
            except:
                print('ERROR: Unable to read polar data file {:s}'.format(fn))
                exit()
        airfoil = pc.set[iset][iairfoil]
        ada = aero_damp_analyzer(airfoil,fn,itype,aoas,psis,beta,gama,phi,k)
        plt.show()
        