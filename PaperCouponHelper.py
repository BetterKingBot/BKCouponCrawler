import os
import traceback
from datetime import datetime
from typing import List

import Helper
from Helper import getTimezone, loadJson

from UtilsCouponsDB import Coupon

""" Helper for adding paper coupons to the coupon system. """


def main() -> List[Coupon]:
    extrainfomap = {
        "08.11.2024": {
            "thx": "Danke an die MyDealz User DerShitstorm und rote_rakete: mydealz.de/deals/burger-king-coupons-gultig-vom-sa-07092024-bis-fr-08112024-2418876#reply-49124677",
            "start_date": "07.09.2024"
        },
        "31.12.2024": {
            "thx": "Danke an den MyDealz User BubbleBobble: mydealz.de/deals/burger-king-coupons-gultig-vom-sa-09112024-bis-fr-10012025-2452049",
            "start_date": "09.11.2024"
        }
    }

    # Pfad zum Ordner "paper_coupon_data"
    folder_path = 'paper_coupon_data'

    # Liste für alle JSON-Dateien im Ordner
    json_files = [os.path.join(folder_path, file) for file in os.listdir(folder_path) if file.endswith('.json')]
    validcoupons = []
    if len(json_files) == 0:
        print("Found zero paper coupon json sources")
        return validcoupons

    for json_file in json_files:
        index = 0
        try:
            papercs = loadJson(json_file)
            expireDates = set()
            for paperc in papercs:
                expiredateStr = paperc['expireDate']
                expireDates.add(expiredateStr)
                extrainfo = extrainfomap.get(expiredateStr)
                start_dateStr = extrainfo['start_date'] if extrainfo is not None else None
                thankyouText = extrainfo['thx'] if extrainfo is not None else None
                coupon = Coupon.wrap(paperc)
                # Do some minor corrections
                coupon.title = coupon.title.replace("*", "")
                coupon.id = paperc['uniqueID']  # Set custom uniqueID otherwise couchDB will create one later -> This is not what we want to happen!!
                price = paperc['price']
                if price == 0:
                    coupon.price = None
                    coupon.staticReducedPercent = 50
                if start_dateStr is not None:
                    startdate = datetime.strptime(start_dateStr, '%d.%m.%Y').astimezone(getTimezone())
                    coupon.timestampStart = startdate.timestamp()
                else:
                    print(f"DEV U FORGOT TO ADD START_DATE FOR {expiredateStr}")
                expiredate = datetime.strptime(expiredateStr + " 23:59:59", '%d.%m.%Y %H:%M:%S').astimezone(getTimezone())
                coupon.timestampExpire = expiredate.timestamp()
                coupon.type = Helper.CouponType.PAPER
                if thankyouText is not None:
                    coupon.description = thankyouText
                else:
                    print(f"DEV U FORGOT PAPER THANK YOU FOR {expiredateStr}")
                # Only add coupon if it is valid
                if coupon.isExpired():
                    continue
                validcoupons.append(coupon)
                index += 1
            # Log inconsistent stuff
            if len(expireDates) != 1:
                print(f"Warnung: Ungleiche Ablaufdaten entdeckt! {expireDates}")
            if len(papercs) != 48:
                print(f"Warnung | Erwartete Anzahl Papiercoupons: 48 | Gefunden: {len(papercs)}")
        except:
            traceback.print_exc()
            print(f"Fehler beim Laden oder Verarbeiten der Papiercoupons {json_file} | Index {index}")
            continue
    return validcoupons


if __name__ == "__main__":
    main()


def getValidPaperCouponList() -> list:
    return main()


def getValidPaperCouponDict() -> dict:
    couponDict = {}
    list = main()
    for coupon in list:
        couponDict[coupon.id] = coupon
    return couponDict
