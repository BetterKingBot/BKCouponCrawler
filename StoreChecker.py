import httpx


from BaseUtils import logging

""" Helper tools to find storeIDs of stores via which we can obtain a list of coupons via API. """
""" Returns List of stores """
HEADERS_OLD = {"User-Agent": "BurgerKing/6.7.0 (de.burgerking.kingfinder; build:432; Android 8.0.0) okhttp/3.12.3"}

stores = httpx.get('https://api.burgerking.de/api/o2uvrPdUY57J5WwYs6NtzZ2Knk7TnAUY/v2/de/de/stores/', headers=HEADERS_OLD).json()

storeIDsToCheck = []
""" Collect all storeIDs that provide coupons """
for store in stores:
    properties = store['properties']
    if 'mobileOrdering' in properties:
        storeIDsToCheck.append(store['id'])

if len(storeIDsToCheck) == 0:
    logging.warning("Failed to find any storeIDs with coupons --> Checking ALL")
    for store in stores:
        properties = store['properties']
        storeIDsToCheck.append(store['id'])

""" 2021-02-15: The first 3 stores that supported mobile ordering were: [682, 4108, 514] """
"""
2021-11-23:
StoreIDs with coupons: [682, 4108, 403, 409, 437, 441, 455, 471, 486, 505, 512, 514, 550, 1033, 571, 578, 597, 627, 653, 698, 711, 714, 737, 744, 829, 848, 897, 929, 994, 995, 1010, 1001, 997, 1024, 1044, 3057, 1059, 12971, 13948, 9447, 11674, 11041, 11985, 11742, 12267, 13237, 16017, 16018, 382, 393]
"""
# storeIDsToCheck = [682, 4108, 514]
storeIDsConfirmed = []
couponIDs = []
index = -1
printNewCoupons = False
for storeID in storeIDsToCheck:
    index += 1
    if index > 0:
        # time.sleep(5)
        pass
    logging.info("Checking coupons of store " + str(index + 1) + "/" + str(len(storeIDsToCheck)) + " | " + str(storeID))
    apiResponse = httpx.get('https://mo.burgerking-app.eu' + '/api/v2/stores/' + str(storeID) + '/menu', headers=HEADERS_OLD).json()
    """ E.g. response for storeIDs without mobileOrdering: {"errors":[{"code":19,"message":"Record not found.","details":{"TillsterStore":null}}]} """
    coupons = apiResponse.get("coupons")
    if coupons is None:
        continue
    logging.info("Store provides coupons: " + str(storeID))
    storeIDsConfirmed.append(storeID)
    for coupon in coupons:
        uniqueCouponID = coupon['promo_code']
        if uniqueCouponID not in couponIDs:
            couponIDs.append(uniqueCouponID)
            if printNewCoupons:
                print("Found couponID which is not present in coupons of first checked store: " + uniqueCouponID)
    # Print all new coupons we find after we've crawled the first store
    printNewCoupons = True

logging.info("StoreIDs with coupons: " + str(storeIDsConfirmed))
logging.info("All couponIDs: " + str(couponIDs))

print("StoreChecker done")
