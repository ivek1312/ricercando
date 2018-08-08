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
* ipywidgets
* bokeh
* paramnb
* colorcet
* geoviews (available from conda)

[Orange]: https://orange.biolab.si/download/

Installation of prerequisites using conda:

    conda install -c conda-forge -c ioam -c pyviz orange3 pandas ipywidgets geoviews bokeh=0.13.0 colorcet param=1.7.0 paramnb qgrid=1.0.5 scikit-garden

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

Then issue `git pull` within _ricercando_ directory every now and then.
The alternative is to re-run `pip install git+https://github.com/ivek1312/ricercando`
command whenever updating is desired.

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
This project has received funding from the European Union’s Horizon 2020 research and innovation programme.

Copyright (c) 2018, [Faculty of Computer and Information Science]: http://www.fri.uni-lj.si/en University of Ljubljana, Slovenia
Contact: Veljko Pejovic,  <veljko.pejovic@fri.uni-lj.si>

Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is hereby granted, provided that the above copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
