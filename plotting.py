import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Rectangle

def plot_spectra(pbands, rboaimg, rtoaimg, pixels, title):
    # Plot data
    plt.figure(figsize=(10,5))
    ax = plt.gca()
    colorb = np.array(['darkblue','darkred','grey','red','mediumseagreen','blue','pink','darkgreen','teal','pink','cyan','purple','brown'])
    for i,pixel in enumerate(pixels):
        if rboaimg is not None:
            ax.plot(pbands, rboaimg[:,pixel,pixel], marker='s', color=colorb[i], lw=0.5, alpha=0.8)
        if rtoaimg is not None:
            ax.plot(pbands, rtoaimg[:,pixel,pixel], marker='^', color=colorb[i+1], lw=0.5, alpha=0.8)
    plt.title(title) 
    plt.xlabel("Wavelength [nm]",size=14)
    ax.set_ylabel("Reflectance [sr-1]")

    outfig = 'MESSR-spectra.png'
    plt.savefig(outfig, dpi=300, bbox_inches='tight')
    print("Plot written to: {}".format(outfig))
    plt.show()