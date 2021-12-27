import logging
import os
from datetime import datetime
from enum import Enum
from typing import Union, List

from couchdb.mapping import TextField, FloatField, ListField, IntegerField, BooleanField, Document, DictField, Mapping

from CouponCategory import BotAllowedCouponSources
from Helper import getTimezone, getCurrentDate, getFilenameFromURL, SYMBOLS


class Coupon(Document):
    plu = TextField()
    uniqueID = TextField()
    price = FloatField()
    priceCompare = FloatField()
    staticReducedPercent = FloatField()
    title = TextField()
    titleShortened = TextField()
    timestampStart = FloatField()
    timestampExpire = FloatField()  # Internal expire-date
    timestampExpire2 = FloatField()  # Expire date used by BK in their apps -> "Real" expire date.
    dateFormattedStart = TextField()
    dateFormattedExpire = TextField()
    dateFormattedExpire2 = TextField()
    imageURL = TextField()
    productIDs = ListField(IntegerField())
    source = IntegerField()
    containsFriesOrCoke = BooleanField()
    isNew = BooleanField(default=False)
    isHidden = BooleanField(default=False)  # Typically only available for App coupons
    isUnsafeExpiredate = BooleanField(default=False)  # Set this if timestampExpire2 is a self made up date
    isEatable = BooleanField(default=True)  # E.g. False for Payback coupons
    description = TextField()


class User(Document):

    def testMethod(self):
        return None

    settings = DictField(
        Mapping.build(
            displayQR=BooleanField(default=False),
            displayHiddenAppCouponsWithinGenericCategories=BooleanField(default=False),
            displayCouponCategoryPayback=BooleanField(default=True),
            notifyWhenFavoritesAreBack=BooleanField(default=False),
            notifyWhenNewCouponsAreAvailable=BooleanField(default=False),
            highlightFavoriteCouponsInButtonTexts=BooleanField(default=True),
            highlightNewCouponsInCouponButtonTexts=BooleanField(default=True),
            autoDeleteExpiredFavorites=BooleanField(default=False),  # TODO: Implement this
            enableBetaFeatures=BooleanField(default=False)
        )
    )
    favoriteCoupons = DictField()


class InfoEntry(Document):
    timestampLastCrawl = FloatField(name="timestamp_last_crawl", default=-1)
    timestampLastChannelUpdate = FloatField(name="timestamp_last_telegram_channel_update", default=-1)
    informationMessageID = TextField(name="channel_last_information_message_id")
    couponTypeOverviewMessageIDs = ListField(TextField(), name="channel_last_coupon_type_overview_message_ids_")
    messageIDsToDelete = ListField(IntegerField(), name="message_ids_to_delete", default=[])


class ChannelCoupon(Document):
    # names are given to ensure compatibility to older DB versions. TODO: Remove this whenever possible. To do this, channel needs to be manually wiped with current/older version. Then these names can be removed and channel update can be sent out.
    uniqueIdentifier = TextField(name="coupon_unique_identifier")
    messageIDs = ListField(IntegerField(), name="coupon_message_ids")
    timestampMessagesPosted = FloatField(name="timestamp_tg_messages_posted", default=-1)


class CouponSortMode(Enum):
    PRICE = 0
    MENU_PRICE = 1
    SOURCE_MENU_PRICE = 2


def couponDBGetExpireDatetime(coupon: Coupon) -> Union[datetime, None]:
    """ First check for artificial expire-date which is usually shorter than the other date - prefer that! """
    if coupon.timestampExpire2 is not None:
        return datetime.fromtimestamp(coupon.timestampExpire2, getTimezone())
    elif coupon.timestampExpire is not None:
        return datetime.fromtimestamp(coupon.timestampExpire, getTimezone())
    else:
        # This should never happen
        logging.warning("Found coupon without expiredate: " + coupon.id)
        return None


def couponDBIsValid(coupon: Coupon) -> bool:
    expireDatetime = couponDBGetExpireDatetime(coupon)
    if expireDatetime is None:
        # Coupon without expire-date = invalid --> Should never happen
        return False
    else:
        return expireDatetime > getCurrentDate()


def couponDBGetExpireDateFormatted(coupon: Coupon, fallback=None) -> Union[str, None]:
    if coupon.dateFormattedExpire2 is not None:
        return coupon.dateFormattedExpire2
    elif coupon.dateFormattedExpire is not None:
        return coupon.dateFormattedExpire
    else:
        return fallback


def couponDBGetImageQR(coupon: Coupon):
    path = couponDBGetImagePathQR(coupon)
    if os.path.exists(path):
        return open(path, mode='rb')
    else:
        return None


def getImageBasePath() -> str:
    return "crawler/images/couponsproductive"


def couponDBGetImagePathQR(coupon: Coupon) -> str:
    return getImageBasePath() + "/" + coupon.id + "_QR.png"


def couponDBGetImagePath(coupon: Coupon) -> str:
    if coupon.imageURL.startswith('file://'):
        # Image should be present in local storage: Use pre-given path
        return coupon.imageURL.replace('file://', '')
    else:
        return getImageBasePath() + "/" + coupon.id + "_" + getFilenameFromURL(coupon.imageURL)


def couponDBGetUniqueIdentifier(coupon: Coupon) -> str:
    """ Returns an unique identifier String which can be used to compare coupon objects. """
    expiredateStr = couponDBGetExpireDateFormatted(coupon, 'undefined')
    return coupon.id + '_' + ("undefined" if coupon.plu is None else coupon.plu) + '_' + expiredateStr + '_' + coupon.imageURL


def couponDBGetPLUOrUniqueID(coupon: Coupon) -> str:
    """ Returns PLU if existant, returns UNIQUE_ID otherwise. """
    if coupon.plu is not None:
        return coupon.plu
    else:
        return coupon.id


def couponDBGetComparableValue(coupon: Coupon) -> str:
    """ Returns value which can be used to compare given coupon object to another one.
     This might be useful in the future to e.g. find coupons that contain exactly the same products as others.
      Do NOT use this to compare multiple coupon datasets! Use couponDBGetUniqueIdentifier instead!
      """
    return coupon.title.lower() + str(coupon.price)


def couponDBGetPriceFormatted(coupon: Coupon, fallback=None) -> Union[str, None]:
    if coupon.price is not None:
        return getFormattedPrice(coupon.price)
    else:
        return fallback


def couponDBGetPriceCompareFormatted(coupon: Coupon, fallback=None) -> Union[str, None]:
    if coupon.priceCompare is not None:
        return getFormattedPrice(coupon.priceCompare)
    else:
        return fallback


def couponDBGetReducedPercentageFormatted(coupon: Coupon, fallback=None) -> Union[str, None]:
    """ Returns price reduction in percent if bothb the original price and the reduced/coupon-price are available.
     E.g. "-39%" """
    if coupon.price is not None and coupon.priceCompare is not None:
        return '-' + f'{(1 - (coupon.price / coupon.priceCompare)) * 100:2.0f}'.replace('.', ',') + '%'
    elif coupon.staticReducedPercent is not None:  # Sometimes we don't have a compare-price but the reduce amount is pre-given via App-API.
        return '-' + f'{coupon.staticReducedPercent:2.0f}' + '%'
    else:
        return fallback


def getFormattedPrice(price: float) -> str:
    return f'{(price / 100):2.2f}'.replace('.', ',') + '€'


def isValidBotCoupon(coupon: Coupon) -> bool:
    """ Checks if the given coupon can be used in bot e.g. is from allowed source (App/Paper) and is valid. """
    return coupon.source in BotAllowedCouponSources and couponDBIsValid(coupon)


def getCouponsTotalPrice(coupons: List[Coupon]) -> float:
    """ Returns the total summed price of a list of coupons. """
    totalSum = 0
    for coupon in coupons:
        if coupon.price is not None:
            totalSum += coupon.price
    return totalSum


def getCouponsSeparatedByType(coupons: dict) -> dict:
    couponsSeparatedByType = {}
    for couponSource in BotAllowedCouponSources:
        couponsTmp = list(filter(lambda x: x[Coupon.source.name] == couponSource, list(coupons.values())))
        couponsSeparatedByType[couponSource] = couponsTmp
    return couponsSeparatedByType


def generateCouponShortText(coupon: Coupon, highlightIfNew: bool) -> str:
    """ Returns e.g. "Y15 | 2Whopper+M🍟+0,4Cola | 8,99€" """
    couponText = ''
    if coupon.isNew and highlightIfNew:
        couponText += SYMBOLS.NEW
    couponText += couponDBGetPLUOrUniqueID(coupon) + " | " + coupon.titleShortened
    priceFormatted = couponDBGetPriceFormatted(coupon)
    reducedPercent = couponDBGetReducedPercentageFormatted(coupon)
    if priceFormatted is not None:
        couponText += " | " + priceFormatted
    elif reducedPercent is not None:
        # Fallback for coupons without given price (rare case) -> Show reduced percent instead (if given)
        couponText += " | " + reducedPercent
    return couponText


def generateCouponShortTextFormatted(coupon: Coupon, highlightIfNew: bool) -> str:
    """ Returns e.g. "<b>Y15</b> | 2Whopper+M🍟+0,4Cola | 8,99€" """
    couponText = ''
    if coupon.isNew and highlightIfNew:
        couponText += SYMBOLS.NEW
    couponText += "<b>" + couponDBGetPLUOrUniqueID(coupon) + "</b> | " + coupon.titleShortened
    priceFormatted = couponDBGetPriceFormatted(coupon)
    reducedPercent = couponDBGetReducedPercentageFormatted(coupon)
    if priceFormatted is not None:
        couponText += " | " + priceFormatted
    elif reducedPercent is not None:
        # Fallback for coupons without given price (rare case) -> Show reduced percent instead (if given)
        couponText += " | " + reducedPercent
    return couponText


def generateCouponShortTextFormattedWithHyperlinkToChannelPost(coupon: Coupon, highlightIfNew: bool, publicChannelName: str, messageID: int) -> str:
    """ Returns e.g. "Y15 | 2Whopper+M🍟+0,4Cola (https://t.me/betterkingpublic/1054) | 8,99€" """
    couponText = "<b>" + couponDBGetPLUOrUniqueID(coupon) + "</b> | <a href=\"https://t.me/" + publicChannelName + '/' + str(
        messageID) + "\">"
    if coupon.isNew and highlightIfNew:
        couponText += SYMBOLS.NEW
    couponText += coupon.titleShortened + "</a>"
    priceFormatted = couponDBGetPriceFormatted(coupon)
    if priceFormatted is not None:
        couponText += " | " + priceFormatted
    percentReduced = couponDBGetReducedPercentageFormatted(coupon)
    if percentReduced is not None:
        couponText += " | " + percentReduced
    return couponText


# def generateCouponLongText(coupon: Coupon, highlightIfNew: bool = True) -> str:
#     """ Returns e.g. "2 Whopper + Mittlere Pommes + 0,4L Cola
#     Y15 | 8,99€ | -25% " """
#     couponText = ''
#     if coupon.isNew and highlightIfNew:
#         couponText += SYMBOLS.NEW
#     couponText += coupon.title
#     couponText += "\n" + couponDBGetPLUOrUniqueID(coupon)
#     priceFormatted = couponDBGetPriceFormatted(coupon)
#     if priceFormatted is not None:
#         couponText += " | " + priceFormatted
#     percentReduced = couponDBGetReducedPercentageFormatted(coupon)
#     if percentReduced is not None:
#         couponText += " | " + percentReduced
#     return couponText


def generateCouponLongTextFormatted(coupon: Coupon) -> str:
    """ Returns e.g. "2 Whopper + Mittlere Pommes + 0,4L Cola
     <b>Y15</b> | 8,99€ | -25% " """
    couponText = ''
    if coupon.isNew:
        couponText += SYMBOLS.NEW
    couponText += coupon.title
    couponText += "\n<b>" + couponDBGetPLUOrUniqueID(coupon) + "</b>"
    priceFormatted = couponDBGetPriceFormatted(coupon)
    if priceFormatted is not None:
        couponText += " | " + priceFormatted
    reducedPercentage = couponDBGetReducedPercentageFormatted(coupon)
    if reducedPercentage is not None:
        couponText += " | " + reducedPercentage
    return couponText


def generateCouponLongTextFormattedWithHyperlinkToChannelPost(coupon: Coupon, publicChannelName: str, messageID: int) -> str:
    """ Returns e.g. "2 Whopper + Mittlere Pommes +0,4L Cola (https://t.me/betterkingpublic/1054)
     <b>Y15</b> | 8,99€ | -25% " """
    couponText = "<a href=\"https://t.me/" + publicChannelName + '/' + str(
        messageID) + "\">"
    if coupon.isNew:
        couponText += SYMBOLS.NEW
    couponText += coupon.title
    couponText += "</a>"
    couponText += "\n<b>" + couponDBGetPLUOrUniqueID(coupon) + "</b>"
    priceFormatted = couponDBGetPriceFormatted(coupon)
    if priceFormatted is not None:
        couponText += " | " + priceFormatted
    reducedPercentage = couponDBGetReducedPercentageFormatted(coupon)
    if reducedPercentage is not None:
        couponText += " | " + reducedPercentage
    return couponText


def generateCouponLongTextFormattedWithDescription(coupon: Coupon, highlightIfNew: bool):
    """
    :param highlightIfNew: Add emoji to text if coupon is new.
    :param coupon: Coupon
    :return: E.g. "<b>B3</b> | 1234 | 13.99€ | -50%\nGültig bis:19.06.2021\nCoupon.description"
    """
    price = couponDBGetPriceFormatted(coupon)
    couponText = ''
    if coupon.isNew and highlightIfNew:
        couponText += SYMBOLS.NEW
    couponText += coupon.title + '\n'
    if coupon.plu is not None:
        couponText += '<b>' + coupon.plu + '</b>' + ' | ' + coupon.id
    else:
        couponText += '<b>' + coupon.id + '</b>'
    if price is not None:
        couponText += ' | ' + price
    reducedPercentage = couponDBGetReducedPercentageFormatted(coupon)
    if reducedPercentage is not None:
        couponText += " | " + reducedPercentage
    """ Expire date should be always given but we can't be 100% sure! """
    expireDateFormatted = couponDBGetExpireDateFormatted(coupon)
    if expireDateFormatted is not None:
        couponText += '\nGültig bis ' + expireDateFormatted
    if coupon.description is not None:
        couponText += "\n" + coupon.description
    return couponText
