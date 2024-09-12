from datetime import datetime

import Helper
from Helper import getTimezone, loadJson

from UtilsCouponsDB import Coupon

""" Helper for adding paper coupons to the coupon system. """


def main() -> list:
    thankyouMap = {"8.11.2024": "Danke an die MyDealz User DerShitstorm und rote_rakete: mydealz.de/deals/burger-king-coupons-gultig-vom-sa-07092024-bis-fr-08112024-2418876#reply-49124677"}
    try:
        papercs = loadJson("paper_coupon_data/coupons.json")
        validcoupons = []
        expireDates = set()
        for paperc in papercs:
            expiredateStr = paperc['expireDate']
            expireDates.add(expiredateStr)
            thankyouText = thankyouMap.get(expiredateStr)
            coupon = Coupon.wrap(paperc)
            # Do some minor corrections
            coupon.title = coupon.title.replace("*", "")
            coupon.id = paperc['uniqueID']  # Set custom uniqueID otherwise couchDB will create one later -> This is not what we want to happen!!
            price = paperc['price']
            if price == 0:
                coupon.price = None
                coupon.staticReducedPercent = 50
            expiredate = datetime.strptime(expiredateStr + " 23:59:59", '%d.%m.%Y %H:%M:%S').astimezone(getTimezone())
            coupon.timestampExpire = expiredate.timestamp()
            coupon.type = Helper.CouponType.PAPER
            if thankyouText is not None:
                coupon.description = thankyouText
            # Only add coupon if it is valid
            if coupon.isValid():
                validcoupons.append(coupon)
        # Log inconsistent stuff
        if len(expireDates) != 1:
            print(f"Warnung: Ungleiche Ablaufdaten entdeckt! {expireDates}")
        if len(papercs) != 48:
            print(f"Warnung | Erwartete Anzahl Papiercoupons: 48 | Gefunden: {len(papercs)}")
        return validcoupons
    except:
        print("Fehler beim Laden oder Verarbeiten der Papiercoupons")
        return []


if __name__ == "__main__":
    main()


def getValidPaperCouponList() -> list:
    return main()


def getValidPaperCouponDict() -> dict:
    list = main()
    couponDict = {}
    for coupon in list:
        couponDict[coupon.id] = coupon
    return couponDict
