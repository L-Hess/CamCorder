# Installation

On Ubuntu 18.04.1 using anaconda, opencv is not distributed with any GUI support anymore?

- conda w/ menpo opencv
- install gui with `pip install opencv-contrib-python`

# TODO:

[X] LED state indicator for online frame lag visualization

[X] Kalman filter for position

[X] Log writer timestamps

[X] position list to deque

[ ] Graph representation to indicate invalid node transitions where possible

[ ] Configuration files for node locations, cameras etc.

[X] Metadata header in shared array

[X] Write tracking result to file

[ ] Prediction termination of filter output on error threshold

[ ] Wrap HexTrack in Qt5 GUI

[X] Search ROI to reduce processing load when having good idea of target location

[ ] Adjust min area to confidence in mouse location. If high confidence,
    area can be smaller, catching partial coverage.
