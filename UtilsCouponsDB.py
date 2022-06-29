import logging
import os
import re
from datetime import datetime
from enum import Enum
from io import BytesIO
from typing import Union, List, Optional

from barcode.ean import EuropeanArticleNumber13
from barcode.writer import ImageWriter
from couchdb.mapping import TextField, FloatField, ListField, IntegerField, BooleanField, Document, DictField, Mapping, \
    DateTimeField
from pydantic import BaseModel

from BotUtils import getImageBasePath
from Helper import getTimezone, getCurrentDate, getFilenameFromURL, SYMBOLS, normalizeString, formatDateGerman, couponTitleContainsFriesOrCoke, BotAllowedCouponTypes, \
    CouponType, \
    formatPrice


class CouponSortCode:
    PRICE = 0
    PRICE_DESCENDING = 1
    MENU_PRICE = 2
    TYPE_MENU_PRICE = 3


class CouponSortMode:

    def __init__(self, sortCode: int, text: str, isDescending: bool = False):
        self.sortCode = sortCode
        self.text = text
        self.isDescending = isDescending


class CouponSortModes:
    PRICE = CouponSortMode(CouponSortCode.PRICE, "Preis aufsteigend")
    PRICE_DESCENDING = CouponSortMode(CouponSortCode.PRICE_DESCENDING, "Preis absteigend", True)
    MENU_PRICE = CouponSortMode(CouponSortCode.MENU_PRICE, "Menü_Preis")
    TYPE_MENU_PRICE = CouponSortMode(CouponSortCode.TYPE_MENU_PRICE, "Typ_Menü_Preis")

    def getAllSortModes(self) -> list:
        return [self.PRICE, self.PRICE_DESCENDING, self.MENU_PRICE, self.TYPE_MENU_PRICE]

    def getSortModeBySortCode(self, sortCode: int) -> Union[CouponSortMode, None]:
        for couponSortMode in self.getAllSortModes():
            if couponSortMode.sortCode == sortCode:
                return couponSortMode
        return None


class Coupon(Document):
    plu = TextField()
    uniqueID = TextField()
    price = FloatField()
    priceCompare = FloatField()
    staticReducedPercent = FloatField()
    title = TextField()
    titleShortened = TextField()
    timestampStart = FloatField()
    timestampExpireInternal = FloatField()  # Internal expire-date
    timestampExpire = FloatField()  # Expire date used by BK in their apps -> "Real" expire date.
    dateFormattedStart = TextField()
    dateFormattedExpireInternal = TextField()
    dateFormattedExpire = TextField()
    imageURL = TextField()
    paybackMultiplicator = IntegerField()
    productIDs = ListField(IntegerField())
    type = IntegerField(name='source')  # Legacy. This is called "type" now!
    containsFriesOrCoke = BooleanField()
    isNew = BooleanField()
    isNewUntilDate = TextField()
    isHidden = BooleanField(default=False)  # Typically only available for App coupons
    isUnsafeExpiredate = BooleanField(
        default=False)  # Set this if timestampExpire is a made up date that is just there to ensure that the coupon is considered valid for a specified time
    description = TextField()
    # TODO: Make use of this once it is possible for users to add coupons to DB via API
    addedVia = IntegerField()

    def getPLUOrUniqueID(self) -> str:
        """ Returns PLU if existant, returns UNIQUE_ID otherwise. """
        if self.plu is not None:
            return self.plu
        else:
            return self.id

    def getFirstLetterOfPLU(self) -> Union[str, None]:
        """ Returns first letter of PLU if PLU is given and starts with a single letter followed by numbers-only. """
        if self.plu is None:
            return None
        # Paper coupons usually only contain one char followed by a 1-2 digit number.
        pluRegEx = re.compile(r'(?i)^([A-Z])\d+$').search(self.plu)
        if not pluRegEx:
            return None
        return pluRegEx.group(1).upper()

    def getNormalizedTitle(self):
        return normalizeString(self.getTitle())

    def getTitle(self):
        return self.title

    def getTitleShortened(self):
        # TODO: Make use of this everywhere
        return self.titleShortened
        # return shortenProductNames(self.title)

    def isExpired(self):
        """ Wrapper """
        if not self.isValid():
            return True
        else:
            return False

    def isExpiredForLongerTime(self):
        """ Using this check, coupons that e.g. expire on midnight and get elongated will not be marked as new because really they aren't. """
        expireDatetime = self.getExpireDatetime()
        if expireDatetime is None:
            return True
        elif getCurrentDate().second - expireDatetime.second > 3600:
            """ 
             Coupon expired over one hour ago -> We consider this a "longer time"
             Using this check, coupons that e.g. expire on midnight and get elongated will not be marked as new because really they aren't.
             """
            return True
        else:
            """ Coupon is not expired or not "long enough". """
            return False

    def isValid(self):
        expireDatetime = self.getExpireDatetime()
        if expireDatetime is None:
            # Coupon without expire-date = invalid --> Should never happen
            return False
        elif expireDatetime > getCurrentDate():
            return True
        else:
            return False

    def isValidForBot(self) -> bool:
        """ Checks if the given coupon can be used in bot e.g. is from allowed source (App/Paper) and is valid. """
        if self.type in BotAllowedCouponTypes and self.isValid():
            return True
        else:
            return False

    def isContainsFriesOrCoke(self) -> bool:
        # TODO: Make use of this
        if couponTitleContainsFriesOrCoke(self.title):
            return True
        else:
            return False

    def getPrice(self) -> Union[float, None]:
        return self.price

    def getPriceCompare(self) -> Union[float, None]:
        return self.priceCompare

    def isEatable(self) -> bool:
        """ If the product(s) this coupon provide(s) is/are not eatable and e.g. just probide a discount like Payback coupons, this will return False, else True. """
        if self.type == CouponType.PAYBACK:
            return False
        else:
            return True

    def isEligibleForDuplicateRemoval(self):
        if self.type == CouponType.PAYBACK:
            return False
        else:
            return True

    def isNewCoupon(self) -> bool:
        """ Determines whether or not this coupon is considered 'new'. """
        if self.isNew is not None:
            # isNew status is pre-given --> Preferably return that
            return self.isNew
        elif self.isNewUntilDate is not None:
            # Check if maybe coupon should be considered as new for X
            try:
                enforceIsNewOverrideUntilDate = datetime.strptime(self.isNewUntilDate + ' 23:59:59',
                                                                  '%Y-%m-%d %H:%M:%S').astimezone(getTimezone())
                if enforceIsNewOverrideUntilDate.timestamp() > datetime.now().timestamp():
                    return True
                else:
                    return False
            except:
                # This should never happen
                logging.warning("Coupon.getIsNew: WTF invalid date format??")
                return False
        else:
            return False

    def getExpireDatetime(self) -> Union[datetime, None]:
        if self.timestampExpire is not None:
            return datetime.fromtimestamp(self.timestampExpire, getTimezone())
        else:
            # This should never happen
            logging.warning("Found coupon without expiredate: " + self.id)
            return None

    def getExpireDateFormatted(self, fallback: Union[str, None] = None) -> Union[str, None]:
        if self.timestampExpire is not None:
            # return self.dateFormattedExpire
            return formatDateGerman(datetime.fromtimestamp(self.timestampExpire))
        else:
            return fallback

    def getStartDateFormatted(self, fallback: Union[str, None] = None) -> Union[str, None]:
        if self.timestampStart is not None:
            return formatDateGerman(datetime.fromtimestamp(self.timestampStart))
        else:
            return fallback

    def getPriceFormatted(self, fallback=None) -> Union[str, None]:
        if self.price is not None:
            return formatPrice(self.price)
        else:
            return fallback

    def getPriceCompareFormatted(self, fallback=None) -> Union[str, None]:
        priceCompare = self.getPriceCompare()
        if priceCompare is not None:
            return formatPrice(priceCompare)
        else:
            return fallback

    def getReducedPercentageFormatted(self, fallback=None) -> Union[str, None]:
        """ Returns price reduction in percent if bothb the original price and the reduced/coupon-price are available.
         E.g. "-39%" """
        priceCompare = self.getPriceCompare()
        if self.price is not None and priceCompare is not None:
            return '-' + f'{(1 - (self.price / priceCompare)) * 100:2.0f}'.replace('.', ',') + '%'
        elif self.staticReducedPercent is not None:  # Sometimes we don't have a compare-price but the reduce amount is pre-given via App-API.
            return '-' + f'{self.staticReducedPercent:2.0f}' + '%'
        elif self.paybackMultiplicator is not None:
            # 0.5 points per euro (= base discount of 0.5% without multiplicator)
            paybackReducedPercent = (0.5 * self.paybackMultiplicator)
            return '-' + f'{paybackReducedPercent:2.1f}' + '%'
        else:
            return fallback

    def getAddedVia(self):
        """ Returns origin of how this coupon got added to DB e.g. API, by admin etc. """
        return self.addedVia

    def getCouponType(self):
        return self.type

    def getUniqueIdentifier(self) -> str:
        """ Returns an unique identifier String which can be used to compare coupon objects. """
        expiredateStr = self.getExpireDateFormatted(fallback='undefined')
        return self.id + '_' + (
            "undefined" if self.plu is None else self.plu) + '_' + expiredateStr + '_' + self.imageURL

    def getComparableValue(self) -> str:
        """ Returns value which can be used to compare given coupon object to another one.
         This might be useful in the future to e.g. find coupons that contain exactly the same products and cost the same price as others.
          Do NOT use this to compare multiple Coupon objects! Use couponDBGetUniqueIdentifier instead!
          """
        return self.getTitle().lower() + str(self.price)

    def getImagePath(self) -> str:
        if self.imageURL.startswith('file://'):
            # Image should be present in local storage: Use pre-given path
            return self.imageURL.replace('file://', '')
        else:
            return getImageBasePath() + "/" + self.id + "_" + getFilenameFromURL(self.imageURL)

    def getImagePathQR(self) -> str:
        return getImageBasePath() + "/" + self.id + "_QR.png"

    def getImageQR(self):
        path = self.getImagePathQR()
        if os.path.exists(path):
            return open(path, mode='rb')
        else:
            # Return fallback --> This should never happen!
            return open('media/fallback_image_missing_qr_image.jpeg', mode='rb')

    def generateCouponShortText(self, highlightIfNew: bool) -> str:
        """ Returns e.g. "Y15 | 2Whopper+M🍟+0,4Cola | 8,99€" """
        couponText = ''
        if self.isNewCoupon() and highlightIfNew:
            couponText += SYMBOLS.NEW
        couponText += self.getPLUOrUniqueID() + " | " + self.getTitleShortened()
        couponText = self.appendPriceInfoText(couponText)
        return couponText

    def generateCouponShortTextFormatted(self, highlightIfNew: bool) -> str:
        """ Returns e.g. "<b>Y15</b> | 2Whopper+M🍟+0,4Cola | 8,99€" """
        couponText = ''
        if self.isNewCoupon() and highlightIfNew:
            couponText += SYMBOLS.NEW
        couponText += "<b>" + self.getPLUOrUniqueID() + "</b> | " + self.getTitleShortened()
        couponText = self.appendPriceInfoText(couponText)
        return couponText

    def generateCouponShortTextFormattedWithHyperlinkToChannelPost(self, highlightIfNew: bool, publicChannelName: str,
                                                                   messageID: int) -> str:
        """ Returns e.g. "Y15 | 2Whopper+M🍟+0,4Cola (https://t.me/betterkingpublic/1054) | 8,99€" """
        couponText = "<b>" + self.getPLUOrUniqueID() + "</b> | <a href=\"https://t.me/" + publicChannelName + '/' + str(
            messageID) + "\">"
        if self.isNewCoupon() and highlightIfNew:
            couponText += SYMBOLS.NEW
        couponText += self.getTitleShortened() + "</a>"
        couponText = self.appendPriceInfoText(couponText)
        return couponText

    def generateCouponLongTextFormatted(self) -> str:
        """ Returns e.g. "2 Whopper + Mittlere Pommes + 0,4L Cola
         <b>Y15</b> | 8,99€ | -25% " """
        couponText = ''
        if self.isNewCoupon():
            couponText += SYMBOLS.NEW
        couponText += self.getTitle()
        couponText += "\n<b>" + self.getPLUOrUniqueID() + "</b>"
        couponText = self.appendPriceInfoText(couponText)
        return couponText

    def generateCouponLongTextFormattedWithHyperlinkToChannelPost(self, publicChannelName: str, messageID: int) -> str:
        """ Returns e.g. "2 Whopper + Mittlere Pommes +0,4L Cola (https://t.me/betterkingpublic/1054)
         <b>Y15</b> | 8,99€ | -25% " """
        couponText = "<a href=\"https://t.me/" + publicChannelName + '/' + str(
            messageID) + "\">"
        if self.isNewCoupon():
            couponText += SYMBOLS.NEW
        couponText += self.getTitle()
        couponText += "</a>"
        couponText += "\n<b>" + self.getPLUOrUniqueID() + "</b>"
        couponText = self.appendPriceInfoText(couponText)
        return couponText

    def generateCouponLongTextFormattedWithDescription(self, highlightIfNew: bool):
        """
        :param highlightIfNew: Add emoji to text if coupon is new.
        :return: E.g. "<b>B3</b> | 1234 | 13.99€ | -50%\nGültig bis:19.06.2021\nCoupon.description"
        """
        couponText = ''
        if self.isNewCoupon() and highlightIfNew:
            couponText += SYMBOLS.NEW
        couponText += self.getTitle() + '\n'
        couponText += self.getPLUInformationFormatted()
        couponText = self.appendPriceInfoText(couponText)
        """ Expire date should be always given but we can't be 100% sure! """
        expireDateFormatted = self.getExpireDateFormatted()
        if expireDateFormatted is not None:
            couponText += '\nGültig bis ' + expireDateFormatted
        if self.description is not None:
            couponText += "\n" + self.description
        return couponText

    def getPLUInformationFormatted(self) -> str:
        """ Returns e.g. <b>123</b> | 67407 """
        if self.plu is not None and self.plu != self.id:
            return '<b>' + self.plu + '</b>' + ' | ' + self.id
        else:
            return '<b>' + self.id + '</b>'

    def appendPriceInfoText(self, couponText: str) -> str:
        priceFormatted = self.getPriceFormatted()
        if priceFormatted is not None:
            couponText += " | " + priceFormatted
        reducedPercentage = self.getReducedPercentageFormatted()
        if reducedPercentage is not None:
            couponText += " | " + reducedPercentage
        return couponText

    def getPriceInfoText(self) -> Union[str, None]:
        priceInfoText = None
        priceFormatted = self.getPriceFormatted()
        if priceFormatted is not None:
            priceInfoText = priceFormatted
        reducedPercentage = self.getReducedPercentageFormatted()
        if reducedPercentage is not None:
            if priceInfoText is None:
                priceInfoText = reducedPercentage
            else:
                priceInfoText += " | " + reducedPercentage
        return priceInfoText


class UserFavoritesInfo:
    """ Helper class for users favorites. """

    def __init__(self, favoritesAvailable: Union[List[Coupon], None] = None,
                 favoritesUnavailable: Union[List[Coupon], None] = None):
        # Do not allow null values when arrays are expected. This makes it easier to work with this.
        if favoritesAvailable is None:
            favoritesAvailable = []
        if favoritesUnavailable is None:
            favoritesUnavailable = []
        self.couponsAvailable = favoritesAvailable
        self.couponsUnavailable = favoritesUnavailable

    def getUnavailableFavoritesText(self) -> Union[str, None]:
        if len(self.couponsUnavailable) == 0:
            return None
        else:
            unavailableFavoritesText = ''
            for coupon in self.couponsUnavailable:
                if len(unavailableFavoritesText) > 0:
                    unavailableFavoritesText += '\n'
                unavailableFavoritesText += coupon.id + ' | ' + coupon.getTitleShortened()
                priceInfoText = coupon.getPriceInfoText()
                if priceInfoText is not None:
                    unavailableFavoritesText += ' | ' + priceInfoText
            return unavailableFavoritesText


class User(Document):
    settings = DictField(
        Mapping.build(
            displayQR=BooleanField(default=True),
            displayBKWebsiteURLs=BooleanField(default=True),
            displayCouponCategoryPayback=BooleanField(default=True),
            displayFeedbackCodeGenerator=BooleanField(default=True),
            displayHiddenAppCouponsWithinGenericCategories=BooleanField(default=False),
            notifyWhenFavoritesAreBack=BooleanField(default=False),
            notifyWhenNewCouponsAreAvailable=BooleanField(default=False),
            highlightFavoriteCouponsInButtonTexts=BooleanField(default=True),
            highlightNewCouponsInCouponButtonTexts=BooleanField(default=True),
            hideDuplicates=BooleanField(default=False),
            autoDeleteExpiredFavorites=BooleanField(default=False),
            enableBetaFeatures=BooleanField(default=False)
        )
    )
    botBlockedCounter = IntegerField(default=0)
    easterEggCounter = IntegerField(default=0)
    favoriteCoupons = DictField(default={})
    paybackCard = DictField(
        Mapping.build(
            paybackCardNumber=TextField(),
            addedDate=DateTimeField()
        ))

    def hasProbablyBlockedBot(self) -> bool:
        if self.botBlockedCounter > 0:
            return True
        else:
            return False

    def hasDefaultSettings(self) -> bool:
        for settingKey, settingValue in self["settings"].items():
            settingInfo = USER_SETTINGS_ON_OFF.get(settingKey)
            if settingInfo is None:
                # Ignore keys that aren't covered in our settings map
                continue
            elif settingValue != settingInfo['default']:
                return False

        return True

    def hasFoundEasterEgg(self) -> bool:
        if self.easterEggCounter > 0:
            return True
        else:
            return False

    def isFavoriteCoupon(self, coupon: Coupon):
        """ Checks if given coupon is users' favorite """
        return self.isFavoriteCouponID(coupon.id)

    def isFavoriteCouponID(self, couponID: str):
        if couponID in self.favoriteCoupons:
            return True
        else:
            return False

    def addFavoriteCoupon(self, coupon: Coupon):
        self.favoriteCoupons[coupon.id] = coupon._data

    def deleteFavoriteCoupon(self, coupon: Coupon):
        self.deleteFavoriteCouponID(coupon.id)

    def deleteFavoriteCouponID(self, couponID: str):
        del self.favoriteCoupons[couponID]

    def isAllowSendFavoritesNotification(self):
        if self.settings.autoDeleteExpiredFavorites:
            return False
        elif self.settings.notifyWhenFavoritesAreBack:
            return True
        else:
            return False

    def getPaybackCardNumber(self) -> Union[str, None]:
        """ TODO: Can this be considered a workaround or is the mapping made in a stupid way that it does not return "None" for keys without defined defaults??!
          doing User.paybackCard.paybackCardNumber directly would raise an AttributeError! """
        if len(self.paybackCard) > 0:
            return self.paybackCard.paybackCardNumber
        else:
            return None

    def getPaybackCardImage(self) -> bytes:
        ean = EuropeanArticleNumber13(ean='240' + self.getPaybackCardNumber(), writer=ImageWriter())
        file = BytesIO()
        ean.write(file, options={'foreground': 'black'})
        return file.getvalue()

    def addPaybackCard(self, paybackCardNumber: str):
        self.paybackCard.paybackCardNumber = paybackCardNumber
        self.paybackCard.addedDate = datetime.now()

    def deletePaybackCard(self):
        dummyUser = User()
        self.paybackCard = dummyUser.paybackCard

    def getUserFavoritesInfo(self, couponsFromDB: Union[dict, Document]) -> UserFavoritesInfo:
        """
        Gathers information about the given users' favorite available/unavailable coupons.
        Coupons from DB are required to get current dataset of available favorites.
        """
        if len(self.favoriteCoupons) == 0:
            # User does not have any favorites set --> There is no point to look for the additional information
            return UserFavoritesInfo()
        availableFavoriteCoupons = []
        unavailableFavoriteCoupons = []
        for uniqueCouponID, coupon in self.favoriteCoupons.items():
            couponFromProductiveDB = couponsFromDB.get(uniqueCouponID)
            if couponFromProductiveDB is not None and couponFromProductiveDB.isValid():
                availableFavoriteCoupons.append(couponFromProductiveDB)
            else:
                # User chosen favorite coupon has expired or is not in DB
                coupon = Coupon.wrap(coupon)  # We want a 'real' coupon object
                unavailableFavoriteCoupons.append(coupon)
        # Sort all coupon arrays by price
        if self.settings.hideDuplicates:
            availableFavoriteCoupons = removeDuplicatedCoupons(availableFavoriteCoupons)
        availableFavoriteCoupons = sortCouponsByPrice(availableFavoriteCoupons)
        unavailableFavoriteCoupons = sortCouponsByPrice(unavailableFavoriteCoupons)
        return UserFavoritesInfo(favoritesAvailable=availableFavoriteCoupons,
                                 favoritesUnavailable=unavailableFavoriteCoupons)

    def resetSettings(self):
        dummyUser = User()
        self.settings = dummyUser.settings


class InfoEntry(Document):
    timestampLastCrawl = FloatField(default=-1)
    timestampLastChannelUpdate = FloatField(default=-1)
    informationMessageID = TextField()
    couponTypeOverviewMessageIDs = DictField(default={})
    messageIDsToDelete = ListField(IntegerField(), default=[])
    lastMaintenanceModeState = BooleanField()

    def addMessageIDToDelete(self, messageID: int):
        # Avoid duplicates
        if messageID not in self.messageIDsToDelete:
            self.messageIDsToDelete.append(messageID)

    def addMessageIDsToDelete(self, messageIDs: List):
        for messageID in messageIDs:
            self.addMessageIDToDelete(messageID)

    def addCouponCategoryMessageID(self, couponType: int, messageID: int):
        self.couponTypeOverviewMessageIDs.setdefault(couponType, []).append(messageID)

    def getMessageIDsForCouponCategory(self, couponType: int) -> List[int]:
        return self.couponTypeOverviewMessageIDs.get(str(couponType), [])

    def getAllCouponCategoryMessageIDs(self) -> List[int]:
        messageIDs = []
        for messageIDsTemp in self.couponTypeOverviewMessageIDs.values():
            messageIDs += messageIDsTemp
        return messageIDs

    def deleteCouponCategoryMessageIDs(self, couponType: int):
        if str(couponType) in self.couponTypeOverviewMessageIDs:
            del self.couponTypeOverviewMessageIDs[str(couponType)]

    def deleteAllCouponCategoryMessageIDs(self):
        self.couponTypeOverviewMessageIDs = {}


class ChannelCoupon(Document):
    """ Represents a coupon posted in a Telegram channel.
     Only contains minimum of required information as information about coupons itself is stored in another DB. """
    uniqueIdentifier = TextField()
    messageIDs = ListField(IntegerField())
    timestampMessagesPosted = FloatField(default=-1)
    channelMessageID_image = IntegerField()
    channelMessageID_qr = IntegerField()
    channelMessageID_text = IntegerField()

    def getMessageIDs(self) -> List[int]:
        messageIDs = []
        if self.channelMessageID_image is not None:
            messageIDs.append(self.channelMessageID_image)
        if self.channelMessageID_qr is not None:
            messageIDs.append(self.channelMessageID_qr)
        if self.channelMessageID_text is not None:
            messageIDs.append(self.channelMessageID_text)
        return messageIDs

    def deleteMessageIDs(self):
        # Nullification
        self.channelMessageID_image = None
        self.channelMessageID_qr = None
        self.channelMessageID_text = None

    def getMessageIDForChatHyperlink(self) -> Union[None, int]:
        return self.channelMessageID_image


def getCouponsTotalPrice(coupons: List[Coupon]) -> float:
    """ Returns the total summed price of a list of coupons. """
    totalSum = 0
    for coupon in coupons:
        if coupon.price is not None:
            totalSum += coupon.price
    return totalSum


def getCouponsSeparatedByType(coupons: dict) -> dict:
    """ Returns dict containing lists of coupons by type """
    couponsSeparatedByType = {}
    for couponType in BotAllowedCouponTypes:
        couponsTmp = list(filter(lambda x: x[Coupon.type.name] == couponType, list(coupons.values())))
        if couponsTmp is not None and len(couponsTmp) > 0:
            couponsSeparatedByType[couponType] = couponsTmp
    return couponsSeparatedByType


def sortCouponsByPrice(couponList: Union[List[Coupon], dict], descending: bool = False) -> List[Coupon]:
    """Sort by price -> But price is not always given -> Place items without prices at the BEGINNING of each list."""
    if isinstance(couponList, dict):
        couponList = couponList.values()
    if descending:
        return sorted(couponList,
                      key=lambda x: -1 if x.get(Coupon.price.name, -1) is None else x.get(Coupon.price.name, -1), reverse=True)
    else:
        return sorted(couponList,
                      key=lambda x: -1 if x.get(Coupon.price.name, -1) is None else x.get(Coupon.price.name, -1))


class CouponFilter(BaseModel):
    """ removeDuplicates: Enable to filter duplicated coupons for same products - only returns cheapest of all
     If the same product is available as paper- and app coupon, App coupon is preferred."""
    activeOnly: Optional[bool] = True
    containsFriesAndCoke: Optional[Union[bool, None]] = None
    removeDuplicates: Optional[
        bool] = False  # Enable to filter duplicated coupons for same products - only returns cheapest of all
    allowedCouponTypes: Optional[Union[List[int], None]] = None  # None = allow all sources!
    isNew: Optional[Union[bool, None]] = None
    isHidden: Optional[Union[bool, None]] = None
    sortMode: Optional[Union[None, int]]


def getCouponTitleMapping(coupons: Union[dict, list]) -> dict:
    """ Maps normalized coupon titles to coupons with the goal of being able to match coupons by title
    e.g. to find duplicates or coupons with different IDs containing the same products. """
    if isinstance(coupons, dict):
        coupons = coupons.values()
    couponTitleMappingTmp = {}
    for coupon in coupons:
        couponTitleMappingTmp.setdefault(coupon.getNormalizedTitle(), []).append(coupon)
    return couponTitleMappingTmp


USER_SETTINGS_ON_OFF = {
    # TODO: Obtain these Keys and default values from "User" Mapping class and remove this mess!
    "notifyWhenFavoritesAreBack": {
        "description": "Favoriten Benachrichtigungen",
        "default": False
    },
    "notifyWhenNewCouponsAreAvailable": {
        "description": "Benachrichtigung bei neuen Coupons",
        "default": False
    },
    "displayQR": {
        "description": "QR Codes zeigen",
        "default": True
    },
    "displayHiddenAppCouponsWithinGenericCategories": {
        "description": "Versteckte App Coupons in Kategorien zeigen*¹",
        "default": False
    },
    "displayCouponCategoryPayback": {
        "description": "Payback Coupons/Karte im Hauptmenü zeigen",
        "default": True
    },
    "displayFeedbackCodeGenerator": {
        "description": "Feedback Code Generator im Hauptmenü zeigen",
        "default": True
    },
    "displayBKWebsiteURLs": {
        "description": "BK Verlinkungen im Hauptmenü zeigen",
        "default": True
    },
    "highlightFavoriteCouponsInButtonTexts": {
        "description": "Favoriten in Buttons mit " + SYMBOLS.STAR + " markieren",
        "default": True
    },
    "highlightNewCouponsInCouponButtonTexts": {
        "description": "Neue Coupons in Buttons mit " + SYMBOLS.NEW + " markieren",
        "default": True
    },
    "autoDeleteExpiredFavorites": {
        "description": "Abgelaufene Favoriten automatisch löschen",
        "default": False
    },
    "hideDuplicates": {
        "description": "Duplikate ausblenden |App CP bevorz.",
        "default": False
    }
}

# Enable this to show BETA setting to users --> Only enable this if there are beta features available
# 2022-02-19: Keep this enabled as a dummy although there are no BETA features as disabling it would possibly render the "Reset settings to default" function useless
DISPLAY_BETA_SETTING = False

""" This is a helper for basic user on/off settings """
if DISPLAY_BETA_SETTING:
    USER_SETTINGS_ON_OFF["enableBetaFeatures"] = {
        "description": "Beta Features aktivieren",
        "default": False
    }


def removeDuplicatedCoupons(coupons: Union[list, dict]) -> dict:
    couponTitleMappingTmp = getCouponTitleMapping(coupons)
    # Now clean our mapping: Sometimes one product may be available twice with multiple prices -> We want exactly one mapping per title
    couponsWithoutDuplicates = {}
    for normalizedTitle, coupons in couponTitleMappingTmp.items():
        couponsForDuplicateRemoval = []
        for coupon in coupons:
            if coupon.isEligibleForDuplicateRemoval():
                couponsForDuplicateRemoval.append(coupon)
            else:
                # We cannot remove this coupon as duplicate by title -> Add it to our final results list
                couponsWithoutDuplicates[coupon.id] = coupon
        # Check if anything is left to do
        if len(couponsForDuplicateRemoval) == 0:
            continue
        # Sort these ones by price and pick the first (= cheapest) one for our mapping.
        isDifferentPrices = False
        firstPrice = None
        appCoupon = None
        if len(couponsForDuplicateRemoval) == 1:
            coupon = couponsForDuplicateRemoval[0]
            couponsWithoutDuplicates[coupon.id] = coupon
            continue
        for coupon in couponsForDuplicateRemoval:
            if firstPrice is None:
                firstPrice = coupon.getPrice()
            elif coupon.getPrice() is not None and coupon.getPrice() != firstPrice:
                isDifferentPrices = True
            if coupon.type == CouponType.APP:
                appCoupon = coupon
        if isDifferentPrices:
            # Prefer cheapest coupon
            couponsSorted = sortCouponsByPrice(couponsForDuplicateRemoval)
            coupon = couponsSorted[0]
        elif appCoupon is not None:
            # Same prices but different sources -> Prefer App coupon
            coupon = appCoupon
        else:
            # Same prices but all coupons are from the same source -> Should never happen but we'll cover it anyways -> Select first item.
            coupon = couponsForDuplicateRemoval[0]
        couponsWithoutDuplicates[coupon.id] = coupon
    numberofRemovedDuplicates = len(coupons) - len(couponsWithoutDuplicates)
    logging.debug("Number of removed duplicates: " + str(numberofRemovedDuplicates))
    return couponsWithoutDuplicates
