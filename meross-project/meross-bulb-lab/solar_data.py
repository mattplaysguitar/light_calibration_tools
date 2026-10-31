from astral import LocationInfo
from astral.sun import sun
import datetime



def location():
    city = LocationInfo("Los Alamos,", "New Mexico USA", "Denver", 35.89, -106.116)

    print(f'Information for {city.name} {city.region} {city.timezone}')
    s = sun(city.observer, datetime.datetime.now())
    print(s)

