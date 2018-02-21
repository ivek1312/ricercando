RICERCANDO - Network Measurement Analysis Toolbox
===============

[![Build Status](https://travis-ci.org/ivek1312/ricercando.svg?branch=master)](https://travis-ci.org/ivek1312/ricercando)

The toolbox consists of:
* A Python 3 utility library (Ricercando) for querying, analyzing, and visualizing [MONROE] data.
* An Orange add-on for accessing MONROE data, either from an Influx DB database or a locally stored Dataframe file, and for Significant Group analysis.
* Jupyter notebooks for rapid time-series and geographical analysis of MONROE data, and for automatic detection of anomalies.
* Utility scripts for managing a local copy of MONROE data using Influx DB. 

[MONROE]: https://www.monroe-project.eu/

Prerequisites
------------

To use Ricercando toolbox within Orange data mining suite, install [Orange] 3.9+ first.  

To use time-series and visualisation notebooks, install the following Python packages:
* pandas
* ipywidgets v6.0.1
* bokeh v0.12.14dev6 (available from conda)
* paramnb
* colorcet
* geoviews (available from conda)

[Orange]: https://orange.biolab.si/download/

Installation
------------

Run the following command line in the Python 3 environment of choice:

    pip install git+https://github.com/ivek1312/ricercando

As the project API is as of yet considered unstable, we recommend installing
in development mode:
    
    git clone https://github.com/ivek1312/ricercando
    cd ricercando
    pip install -e .
    
    # Run tests to confirm the package is installed correctly
    python setup.py test

Then issue `git pull` within _ricercando_ directory every now and
then. The alternative is to re-run above `pip install git+...` command
whenever updating is desired.

Usage
-----

For help on [how to query data], see the relevant Jupyter notebook.

Instructions set up your own [MONROE data copy in an Influx DB].

Visualisation Jupyter notebooks are in the [_notebooks_ directory].

For using Ricercando add-on in Orange, see examples in [_workflows_ directory].

[how to query data]: notebooks/data.ipynb
[MONROE data copy in an Influx DB]: scripts/
[_notebooks_ directory]: notebooks/
[_workflows_ directory]: workflows/

Credits
------------

Ricercando is a project of the [Faculty of Computer and Information Science], University of Ljubljana, Slovenia. 

[Faculty of Computer and Information Science]: http://www.fri.uni-lj.si/en
