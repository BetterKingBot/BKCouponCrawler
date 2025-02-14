import logging
import os
import re
from datetime import datetime
from enum import Enum
from typing import Union, List

from couchdb.mapping import TextField, FloatField, ListField, IntegerField, BooleanField, Document

from BotUtils import getImageBasePath
from Helper import getTimezone, getCurrentDate, getFilenameFromURL, SYMBOLS, formatDateGerman, couponTitleContainsFriesAndDrink, CouponType, \
    formatPrice, couponTitleContainsVeggieFood, shortenProductNames, couponTitleContainsPlantBasedFood, couponTitleContainsChiliCheese
from filters import CouponFilter


class CouponTextRepresentationPLUMode(Enum):
    """ This can be used to define how PLUs in short texts shall be represented. """
    SHORT_PLU = 1
    LONG_PLU = 2
    ALL_PLUS = 3


class CouponSortMode:

    def __init__(self, text: str, isDescending: bool = False):
        self.text = text
        self.isDescending = isDescending

    def getSortCode(self) -> Union[int, None]:
        """ Returns position of current sort mode in array of all sort modes. """
        try:
            return getAllSortModes().index(self)
        except ValueError:
            return None  # Sollte eigentlich nicht vorkommen


class CouponSortModes:
    PRICE = CouponSortMode("Preis " + SYMBOLS.ARROW_UP)
    PRICE_DESCENDING = CouponSortMode("Preis " + SYMBOLS.ARROW_DOWN, isDescending=True)
    DISCOUNT = CouponSortMode("Rabatt " + SYMBOLS.ARROW_UP)
    DISCOUNT_DESCENDING = CouponSortMode("Rabatt " + SYMBOLS.ARROW_DOWN, isDescending=True)
    NEW = CouponSortMode("Neue Coupons " + SYMBOLS.ARROW_UP)
    NEW_DESCENDING = CouponSortMode("Neue Coupons " + SYMBOLS.ARROW_DOWN, isDescending=True)
    MENU_PRICE = CouponSortMode("Menü_Preis")
    TYPE_MENU_PRICE = CouponSortMode("Typ_Menü_Preis")


def getAllSortModes() -> list:
    # Important! The order of this will also determine the sort order which gets presented to the user!
    res = []
    for obj in CouponSortModes.__dict__.values():
        if isinstance(obj, CouponSortMode):
            res.append(obj)
    return res


def getNextSortMode(currentSortMode: CouponSortMode) -> CouponSortMode:
    allSortModes = getAllSortModes()
    if currentSortMode is None:
        return allSortModes[0]
    for index in range(len(allSortModes)):
        sortMode = allSortModes[index]
        if sortMode == currentSortMode:
            if index == (len(allSortModes) - 1):
                # Last sortMode in list --> Return first
                return allSortModes[0]
            else:
                # Return next sortMode
                return allSortModes[index + 1]
    # Fallback, should not be needed
    return currentSortMode


def getSortModeBySortCode(sortCode: int) -> CouponSortMode:
    allSortModes = getAllSortModes()
    if sortCode < len(allSortModes):
        return allSortModes[sortCode]
    else:
        # Fallback
        return allSortModes[0]


class CouponView:

    def getFilter(self) -> CouponFilter:
        return self.couponfilter

    def __init__(self, couponfilter: CouponFilter, includeVeggieSymbol: Union[bool, None] = None, highlightFavorites: Union[bool, None] = None,
                 allowModifyFilter: bool = True, title: str = None):
        self.title = title
        self.couponfilter = couponfilter
        self.includeVeggieSymbol = includeVeggieSymbol
        self.highlightFavorites = highlightFavorites
        self.allowModifyFilter = allowModifyFilter

    def getViewCode(self) -> Union[int, None]:
        """ Returns position of current sort mode in array of all sort modes. """
        couponViews = getAllCouponViews()
        index = 0
        for couponView in couponViews:
            if couponView == self:
                return index
            index += 1
        # This should never happen
        return None


class CouponViews:
    ALL = CouponView(couponfilter=CouponFilter(sortCode=CouponSortModes.MENU_PRICE.getSortCode(), isEatable=True), title="Alle Coupons")
    ALL_WITHOUT_MENU = CouponView(couponfilter=CouponFilter(sortCode=CouponSortModes.PRICE.getSortCode(), containsFriesAndCoke=False, isEatable=True), title="Alle Coupons ohne Menü")
    ALL_WITH_MENU = CouponView(couponfilter=CouponFilter(sortCode=CouponSortModes.PRICE.getSortCode(), containsFriesAndCoke=True, isEatable=True), title="Alle Coupons mit Menü")
    CATEGORY = CouponView(couponfilter=CouponFilter(sortCode=CouponSortModes.MENU_PRICE.getSortCode(), removeDuplicates=False))
    CATEGORY_WITHOUT_MENU = CouponView(couponfilter=CouponFilter(sortCode=CouponSortModes.MENU_PRICE.getSortCode(), containsFriesAndCoke=False, removeDuplicates=False))
    HIDDEN_APP_COUPONS_ONLY = CouponView(
        couponfilter=CouponFilter(sortCode=CouponSortModes.PRICE.getSortCode(), allowedCouponTypes=[CouponType.APP], isHidden=True, removeDuplicates=False), title="App Coupons versteckte")
    VEGGIE = CouponView(couponfilter=CouponFilter(sortCode=CouponSortModes.PRICE.getSortCode(), isVeggie=True, isEatable=True), includeVeggieSymbol=False,
                        title=f"{SYMBOLS.BROCCOLI}Veggie Coupons{SYMBOLS.BROCCOLI}")
    MEAT_WITHOUT_PLANT_BASED = CouponView(couponfilter=CouponFilter(sortCode=CouponSortModes.PRICE.getSortCode(), isPlantBased=False, isEatable=True), title="Fleisch ohne Plant Based Coupons")
    # Dummy item basically only used for holding default sortCode for users' favorites
    FAVORITES = CouponView(couponfilter=CouponFilter(sortCode=CouponSortModes.PRICE.getSortCode(), removeDuplicates=False), highlightFavorites=False, allowModifyFilter=False,
                           title=f"{SYMBOLS.STAR}Favoriten{SYMBOLS.STAR}")


def getAllCouponViews() -> List[CouponView]:
    res = []
    for obj in CouponViews.__dict__.values():
        if isinstance(obj, CouponView):
            res.append(obj)
    return res


def getCouponViewByIndex(index: int) -> Union[CouponView, None]:
    allCouponViews = getAllCouponViews()
    if index < len(allCouponViews):
        return allCouponViews[index]
    else:
        # Fallback
        return allCouponViews[0]


COUPON_IS_NEW_FOR_SECONDS = 24 * 60 * 60


class Coupon(Document):
    plu = TextField()
    uniqueID = TextField()
    price = IntegerField()
    priceCompare = IntegerField()
    staticReducedPercent = IntegerField()
    title = TextField()
    subtitle = TextField()
    timestampAddedToDB = FloatField(default=0)
    timestampLastModifiedDB = FloatField(default=0)
    timestampStart = FloatField(default=0)
    timestampExpireInternal = FloatField()  # Internal expire-date
    timestampExpire = FloatField()  # Expire date used by BK in their apps -> "Real" expire date.
    timestampCouponNotInAPIAnymore = FloatField() # 2023-05-09: Not used at this moment
    timestampIsNew = FloatField(default=0)  # Last timestamp from which on this coupon was new
    dateFormattedExpire = TextField()
    imageURL = TextField()
    paybackMultiplicator = IntegerField()
    productIDs = ListField(IntegerField())
    type = IntegerField(name='source')  # Legacy. This is called "type" now!
    isNewUntilDate = TextField()  # Date until which this coupon shall be treated as new. Use this as an override of default handling.
    isHidden = BooleanField(default=False)  # Typically only available for upsell App coupons
    description = TextField()
    # TODO: Make use of this once it is possible for users to add coupons to DB via API
    addedVia = IntegerField()
    tags = ListField(TextField())
    webviewID = TextField()
    webviewURL = TextField()

    def __str__(self):
        return f'{self.id=} | {self.plu} | {self.getTitle()} | {self.getPriceFormatted()} | START: {self.getStartDateFormatted()} | END {self.getExpireDateFormatted()}  | WEBVIEW: {self.getWebviewURL()}'

    def getPLUOrUniqueIDOrRedemptionHint(self) -> str:
        """ Returns PLU if existant, returns UNIQUE_ID otherwise. """
        if self.plu is not None:
            return self.plu
        else:
            showQrHintWhenPLUIsUnavailable = True
            if showQrHintWhenPLUIsUnavailable:
                return 'QR! ' + self.id
            else:
                return self.id

    def getNormalizedTitle(self) -> Union[str, None]:
        title = self.getTitle()
        title = shortenProductNames(title)
        title = re.sub(r'[\W_]+', '', title).lower()
        return title

    def getTitle(self) -> Union[str, None]:
        if self.paybackMultiplicator is not None:
            return f'{self.paybackMultiplicator}Fach auf alle Speisen & Getränke'
        else:
            return self.title

    def getSubtitle(self) -> Union[str, None]:
        return self.subtitle

    def getTitleShortened(self, includeVeggieSymbol: bool = True, includeChiliCheeseSymbol: bool = True) -> Union[str, None]:
        shortenedTitle = shortenProductNames(self.getTitle())
        nutritionSymbolsString = self.getNutritionSymbols(includeVeggieSymbol=includeVeggieSymbol, includeChiliCheeseSymbol=includeChiliCheeseSymbol)
        if nutritionSymbolsString is not None:
            shortenedTitle = nutritionSymbolsString + shortenedTitle
        return shortenedTitle

    def getNutritionSymbols(self, includeMeatSymbol: bool = False, includeVeggieSymbol: bool = True, includeChiliCheeseSymbol: bool = True) -> Union[str, None]:
        """ Returns string of [allowed] nutrition symbols. """
        if not self.isEatable():
            return None
        symbols = []
        if includeMeatSymbol and self.isContainsMeat():
            symbols.append(SYMBOLS.MEAT)
        elif includeVeggieSymbol and self.isVeggie():
            symbols.append(SYMBOLS.BROCCOLI)
        if includeChiliCheeseSymbol and self.isContainsChiliCheese():
            symbols.append(SYMBOLS.CHILI)
        if len(symbols) == 0:
            return None
        symbolsString = "".join(symbols)
        return symbolsString

    def isExpiredForLongerTime(self) -> bool:
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

    def isExpired(self) -> bool:
        expireDatetime = self.getExpireDatetime()
        if expireDatetime is None or expireDatetime < getCurrentDate():
            # Coupon is expired
            return True
        else:
            return False

    def isNotYetActive(self) -> bool:
        startDatetime = self.getStartDatetime()
        if startDatetime is not None and startDatetime > getCurrentDate():
            # Start time hasn't been reached yet -> Coupon is not valid yet
            return True
        else:
            return False

    def isValid(self) -> bool:
        """ If this returns true, we can present the coupon to the user.
         If this returns false, this usually means that the coupon is expired or not yet available. """
        if self.isExpired():
            return False
        elif self.isNotYetActive():
            return False
        else:
            return True

    def isContainsFriesAndDrink(self) -> bool:
        return couponTitleContainsFriesAndDrink(self.getTitle())

    def isContainsChiliCheese(self) -> bool:
        return couponTitleContainsChiliCheese(self.getTitle())

    def isPlantBased(self) -> bool:
        if self.tags is not None:
            # First check tags
            for tag in self.tags:
                tag = tag.lower()
                if 'plant' in tag:
                    return True
        if couponTitleContainsPlantBasedFood(self.getTitle()):
            return True
        else:
            return False

    def isVeggie(self) -> bool:
        if self.isContainsMeat():
            """ 
            Check if coupon contains meat. Some of them are wrongly tagged so ket's fix that by also looking into the product titles.
             """
            return False
        elif self.isPlantBased():
            return True
        elif couponTitleContainsVeggieFood(self.getTitle()):
            # No result? Fallback to other, more unsafe methods.
            return True
        # Last resort: Check if tags contain any useful information.
        if self.tags is not None:
            for tag in self.tags:
                tag = tag.lower()
                if tag == 'sweetkings':
                    return True
        titlelower = self.title.lower()
        if 'sundae' in titlelower:
            return True
        # If in doubt, the product is not veggie
        return False

    def isContainsMeat(self) -> bool:
        """ Returns true if this coupon contains at least one article with meat. """
        """ First check for plant based stuff in title because BK sometimes has wrong tags (e.g. tag contains "chicken" when article is veggie lol)... """
        if self.isPlantBased():
            return False
        elif self.tags is not None:
            for tag in self.tags:
                tag = tag.lower()
                if 'beef' in tag or 'chicken' in tag:
                    return True

        titleLower = self.getTitle().lower()
        if 'chicken' in titleLower:
            return True
        elif 'wings' in titleLower:
            return True
        elif 'beef' in titleLower:
            return True
        else:
            return False

    def getPrice(self) -> Union[float, None]:
        return self.price

    def getPriceCompare(self) -> Union[float, None]:
        """ Returns original price of this product (or all product it contains) without discount. """
        return self.priceCompare

    def isEatable(self) -> bool:
        """ If the product(s) this coupon provide(s) is/are not eatable and e.g. just probide a discount like Payback coupons, this will return False, else True. """
        if self.type == CouponType.PAYBACK:
            return False
        else:
            return True

    def isEligibleForDuplicateRemoval(self):
        """ Returns true if coupon title can be used to remove duplicates.
         """
        if self.type == CouponType.PAYBACK:
            return False
        else:
            return True

    def isNewCoupon(self) -> bool:
        """ Determines whether or not this coupon is considered 'new'. """
        currentTimestamp = getCurrentDate().timestamp()
        timePassedSinceCouponWasAddedToDB = currentTimestamp - self.timestampAddedToDB
        if timePassedSinceCouponWasAddedToDB < COUPON_IS_NEW_FOR_SECONDS:
            return True
        timePassedSinceLastNewTimestamp = currentTimestamp - self.timestampIsNew
        if timePassedSinceLastNewTimestamp < COUPON_IS_NEW_FOR_SECONDS:
            # Coupon has been added just recently and thus can still be considered 'new'
            # couponNewSecondsRemaining = COUPON_IS_NEW_FOR_SECONDS - timePassedSinceLastNewTimestamp
            # print(f'Coupon is considered as new for {formatSeconds(seconds=couponNewSecondsRemaining)} time')
            return True
        timePassedSinceCouponValidityStarted = -1
        if self.timestampStart > 0:
            timePassedSinceCouponValidityStarted = currentTimestamp - self.timestampStart
        if 0 < timePassedSinceCouponValidityStarted < COUPON_IS_NEW_FOR_SECONDS:
            return True
        if self.isNewUntilDate is not None:
            # Check if maybe coupon should be considered as new for X
            try:
                enforceIsNewOverrideUntilDate = datetime.strptime(self.isNewUntilDate + ' 23:59:59',
                                                                  '%Y-%m-%d %H:%M:%S').astimezone(getTimezone())
                if enforceIsNewOverrideUntilDate.timestamp() > getCurrentDate().timestamp():
                    return True
                else:
                    return False
            except:
                # This should never happen
                logging.warning("Coupon.isNewCoupon: WTF invalid date format??")
                return False
        return False

    def getStartDatetime(self) -> Union[datetime, None]:
        """ Returns datetime from which coupon is valid. Not all coupons got a startDatetime. """
        if self.timestampStart is not None and self.timestampStart > 0:
            return datetime.fromtimestamp(self.timestampStart, getTimezone())
        else:
            # Start date must not always be given
            return None

    def getExpireDatetime(self) -> datetime:
        return datetime.fromtimestamp(self.timestampExpire, getTimezone())

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

    def getPriceFormatted(self, fallback: Union[str, None] = None) -> Union[str, None]:
        if self.price is not None:
            return formatPrice(self.price)
        else:
            return fallback

    def getPriceCompareFormatted(self, fallback=None) -> Union[str, None]:
        if self.priceCompare is not None:
            return formatPrice(self.priceCompare)
        else:
            return fallback

    def getReducedPercentage(self) -> Union[float, None]:
        if self.paybackMultiplicator is not None:
            # 0.5 points per euro (= base discount of 0.5% without higher multiplicator)
            return 0.5 * self.paybackMultiplicator
        elif self.price is not None and self.priceCompare is not None:
            return (1 - (self.price / self.priceCompare)) * 100
        elif self.staticReducedPercent is not None:
            return self.staticReducedPercent
        else:
            return None

    def getReducedPercentageFormatted(self, fallback=None) -> Union[str, None]:
        """ Returns price reduction in percent if bothb the original price and the reduced/coupon-price are available.
         E.g. "-39%" """
        reducedPercentage = self.getReducedPercentage()
        if reducedPercentage is not None:
            if self.paybackMultiplicator is not None:
                # Add one decimal point for low percentage reducements such as Payback coupons as those will often only get us like 2.5% discount.
                return '-' + f'{reducedPercentage:2.1f}' + '%'
            else:
                return '-' + f'{reducedPercentage:2.0f}' + '%'
        else:
            return fallback

    def getUniqueIdentifier(self) -> str:
        """ Returns an unique identifier String which can be used to compare coupon objects. """
        plustring = "undefined" if self.plu is None else self.plu
        return f'{self.id}_{plustring}_{self.timestampExpire}_{self.imageURL}'

    def getComparableValue(self) -> str:
        """ Returns value which can be used to compare given coupon object to another one.
         This might be useful in the future to e.g. find coupons that contain exactly the same products and cost the same price as others.
          Do NOT use this to compare multiple Coupon objects! Use couponDBGetUniqueIdentifier instead!
          """
        return self.getTitle().lower() + str(self.price)

    def getImagePath(self) -> Union[str, None]:
        if self.imageURL is None:
            return None
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
            logging.warning(f'Returning fallback QR image for: {path}')
            return open('media/fallback_image_missing_qr_image.jpeg', mode='rb')

    def getWebviewURL(self) -> Union[str, None]:
        if self.webviewID is not None:
            # Default for DB coupons
            return f'https://www.burgerking.de/rewards/offers/{self.webviewID}'
        elif self.webviewURL is not None:
            # Static webview URL e.g. useful for Payback coupons -> Links to mydealz deals
            return self.webviewURL
        else:
            return None

    def getDescription(self) -> Union[str, None]:
        description = self.description
        if self.type == CouponType.PAPER and self.imageURL is not None:
            if description is None:
                description = ""
            elif len(description) > 0:
                description += "\n"
            description += f"{SYMBOLS.WARNING}Achtung!\nDerzeit fehlen die original Produktbilder von Papiercoupons!\nDas Bild dieses Coupons stammt vom gleichnamigen App Coupon! Es gelten die Textangaben in den Buttons und hier im Post-Text, nicht die aus den Bildern!!"
        return description

    def generateCouponShortText(self, highlightIfNew: bool = True, includeVeggieSymbol: bool = True, includeChiliCheeseSymbol: bool = True, plumode: CouponTextRepresentationPLUMode = CouponTextRepresentationPLUMode.ALL_PLUS) -> str:
        """ Returns e.g. "Y15 | 2Whopper+M🍟+0,4Cola | 8,99€" """
        if plumode == CouponTextRepresentationPLUMode.ALL_PLUS and self.plu is not None:
            # All PLUs
            vouchercode = f"{self.plu} | {self.id}"
        elif plumode == CouponTextRepresentationPLUMode.SHORT_PLU and self.plu is not None:
            # Short-PLU
            vouchercode = self.plu
        else:
            # Long-PLU
            vouchercode = self.id
        couponText = ''
        if highlightIfNew and self.isNewCoupon():
            couponText += SYMBOLS.NEW
        couponText += vouchercode + " | " + self.getTitleShortened(includeVeggieSymbol=includeVeggieSymbol, includeChiliCheeseSymbol=includeChiliCheeseSymbol)
        couponText = self.appendPriceInfoText(couponText)
        return couponText

    def generateCouponShortTextFormatted(self, highlightIfNew: bool) -> str:
        """ Returns e.g. "<b>Y15</b> | 2Whopper+M🍟+0,4Cola | 8,99€" """
        couponText = ''
        if highlightIfNew and self.isNewCoupon():
            couponText += SYMBOLS.NEW
        couponText += "<b>" + self.getPLUOrUniqueIDOrRedemptionHint() + "</b> | " + self.getTitleShortened()
        couponText = self.appendPriceInfoText(couponText)
        return couponText

    def generateCouponShortTextFormattedWithHyperlinkToChannelPost(self, highlightIfNew: bool, publicChannelName: str,
                                                                   messageID: int) -> str:
        """ Returns e.g. "Y15 | 2Whopper+M🍟+0,4Cola (https://t.me/betterkingpublic/1054) | 8,99€" """
        couponText = "<b>" + self.getPLUOrUniqueIDOrRedemptionHint() + "</b> | <a href=\"https://t.me/" + publicChannelName + '/' + str(
            messageID) + "\">"
        if highlightIfNew and self.isNewCoupon():
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
        couponText += "\n<b>" + self.getPLUOrUniqueIDOrRedemptionHint() + "</b>"
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
        couponText += "\n<b>" + self.getPLUOrUniqueIDOrRedemptionHint() + "</b>"
        couponText = self.appendPriceInfoText(couponText)
        return couponText

    def generateCouponLongTextFormattedWithDescription(self, highlightIfNew: bool):
        """
        :param highlightIfNew: Add emoji to text if coupon is new.
        :return: E.g. "<b>B3</b> | 1234 | 13.99€ | -50%\nGültig bis:19.06.2021\nCoupon.description"
        """
        couponText = ''
        if highlightIfNew and self.isNewCoupon():
            couponText += SYMBOLS.NEW
        couponText += self.getTitle() + '\n'
        # Add PLU information
        if self.plu is not None and self.plu != self.id:
            couponText += '<b>' + self.plu + '</b>' + ' | ' + self.id
        else:
            # No PLU available or PLU equals ID (This is e.g. the case for Payback coupons)
            couponText += '<b>' + self.id + '</b>'
        couponText = self.appendPriceInfoText(couponText)
        """ Expire date should be always given but we can't be 100% sure! """
        expireDateFormatted = self.getExpireDateFormatted()
        if expireDateFormatted is not None:
            couponText += '\nGültig bis ' + expireDateFormatted
        description = self.getDescription()
        if description is not None:
            couponText += "\n" + description
        webviewURL = self.getWebviewURL()
        if self.plu is None:
            couponText += f'\n{SYMBOLS.WARNING} Keine nennbare PLU verfügbar -> QR Code zeigen!'
        if webviewURL is not None:
            couponText += f"\n{SYMBOLS.ARROW_RIGHT}<a href=\"{webviewURL}\">Webansicht</a>"
        return couponText

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
                unavailableFavoritesText += coupon.id + ' | ' + coupon.getTitleShortened(includeVeggieSymbol=False)
                priceInfoText = coupon.getPriceInfoText()
                if priceInfoText is not None:
                    unavailableFavoritesText += ' | ' + priceInfoText
            return unavailableFavoritesText


MAX_SECONDS_WITHOUT_USAGE_UNTIL_AUTO_ACCOUNT_DELETION = 6 * 30 * 24 * 60 * 60
# X time before account would get deleted, we can inform the user X time before about upcoming auto account deletion
MAX_SECONDS_WITHOUT_USAGE_UNTIL_SEND_WARNING_TO_USER = MAX_SECONDS_WITHOUT_USAGE_UNTIL_AUTO_ACCOUNT_DELETION - 9 * 24 * 60 * 60
MAX_HOURS_ACTIVITY_TRACKING = 48
MAX_TIMES_INFORM_ABOUT_UPCOMING_AUTO_ACCOUNT_DELETION = 3
MIN_SECONDS_BETWEEN_UPCOMING_AUTO_DELETION_WARNING = 2 * 24 * 60 * 60


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
    for coupon in list(coupons.values()):
        typelist = couponsSeparatedByType.setdefault(coupon.type, [])
        typelist.append(coupon)
    return couponsSeparatedByType


def sortCouponsByPrice(couponList: List[Coupon], descending: bool = False) -> List[Coupon]:
    """Sort by price -> But price is not always given -> Place items without prices at the BEGINNING of each list."""
    if isinstance(couponList, dict):
        couponList = couponList.values()
    return sorted(couponList,
                  key=lambda x: -1 if x.getPrice() is None else x.getPrice(), reverse=descending)


def sortCouponsByDiscount(couponList: List[Coupon], descending: bool = False) -> List[Coupon]:
    """Sort by price -> But price is not always given -> Place items without prices at the BEGINNING of each list."""
    if isinstance(couponList, dict):
        couponList = couponList.values()
    return sorted(couponList,
                  key=lambda x: 0 if x.getReducedPercentage() is None else x.getReducedPercentage(), reverse=descending)


def sortCouponsByNew(couponList: List[Coupon], descending: bool = False) -> List[Coupon]:
    """Sort by price -> But price is not always given -> Place items without prices at the BEGINNING of each list."""
    if isinstance(couponList, dict):
        couponList = couponList.values()
    return sorted(couponList,
                  key=lambda x: x.isNewCoupon(), reverse=descending)


def getCouponTitleMapping(coupons: Union[dict, list]) -> dict:
    """ Maps normalized coupon titles to coupons with the goal of being able to match coupons by title
    e.g. to find duplicates or coupons with different IDs containing the same products. """
    if isinstance(coupons, dict):
        coupons = coupons.values()
    couponTitleMappingTmp = {}
    for coupon in coupons:
        normalizedTitle = coupon.getNormalizedTitle()
        dupeslist = couponTitleMappingTmp.setdefault(normalizedTitle, [])
        dupeslist.append(coupon)
    return couponTitleMappingTmp


class SettingCategory:

    def __init__(self, title: str):
        self.title = title

    def getViewCode(self) -> Union[int, None]:
        """ Returns position of current sort mode in array of all sort modes. """
        couponViews = getAllCouponViews()
        index = 0
        for couponView in couponViews:
            if couponView == self:
                return index
            index += 1
        # This should never happen
        return None


class SettingCategories:
    MAIN_MENU = SettingCategory(title='Hauptmenü Buttons')
    GLOBAL_FILTERS = SettingCategory(title='Globale Coupon Filter')
    COUPON_DISPLAY = SettingCategory(title='Anzeigeeinstellungen')
    NOTIFICATIONS = SettingCategory(title='Benachrichtigungen')
    MISC = SettingCategory(title='Sonstige')


USER_SETTINGS_ON_OFF = {
    # TODO: Obtain these Keys and default values from "User" Mapping class and remove this mess!
    "displayCouponCategoryAllCouponsLongListWithLongTitles": {
        "category": SettingCategories.MAIN_MENU,
        "description": f"Kategorie 'Alle Coupons Liste lange Titel + Pics' zeigen",
        "default": False
    },
    "displayCouponCategoryAppCouponsHidden": {
        "category": SettingCategories.MAIN_MENU,
        "description": f"Kategorie 'App Coupons versteckte' zeigen",
        "default": True
    },
    # "displayCouponCategoryMeatWithoutPlantBased": {
    #     "category": SettingCategories.MAIN_MENU,
    #     "description": f"Kategorie Coupons ohne PlantBased ({SYMBOLS.MEAT}) zeigen",
    #     "default": False
    # },
    "displayCouponCategoryVeggie": {
        "category": SettingCategories.MAIN_MENU,
        "description": f"Kategorie Veggie Coupons ({SYMBOLS.BROCCOLI}) zeigen",
        "default": True
    },
    "displayCouponCategoryPayback": {
        "category": SettingCategories.MAIN_MENU,
        "description": "Kategorie Payback Buttons zeigen",
        "default": True
    },
    "displayOffersButton": {
        "category": SettingCategories.MAIN_MENU,
        "description": "Angebote Button zeigen",
        "default": True
    },
    "displayBKWebsiteURLs": {
        "category": SettingCategories.MAIN_MENU,
        "description": "BK Verlinkungen Buttons zeigen",
        "default": True
    },
    "displayFeedbackCodeGenerator": {
        "category": SettingCategories.MAIN_MENU,
        "description": "Feedback Code Generator Button zeigen",
        "default": True
    },
    "displayFAQLinkButton": {
        "category": SettingCategories.MAIN_MENU,
        "description": "FAQ Button zeigen",
        "default": True
    },
    "displayDonateButton": {
        "category": SettingCategories.MAIN_MENU,
        "description": "Spenden Button zeigen",
        "default": True
    },
    "displayAdminButtons": {
        "category": SettingCategories.MAIN_MENU,
        "description": "Admin Buttons anzeigen",
        "default": True
    },
    "displayPlantBasedCouponsWithinGenericCategories": {
        "category": SettingCategories.GLOBAL_FILTERS,
        "description": "Plant Based Coupons in Kategorien zeigen",
        "default": True
    },
    "displayHiddenUpsellingAppCouponsWithinGenericCategories": {
        "category": SettingCategories.GLOBAL_FILTERS,
        "description": "Versteckte App Coupons in Kategorien zeigen*¹",
        "default": True
    },
    "hideDuplicates": {
        "category": SettingCategories.GLOBAL_FILTERS,
        "description": "Duplikate ausblenden | Günstigere CP bevorz.",
        "default": False
    },
    "highlightFavoriteCouponsInButtonTexts": {
        "category": SettingCategories.COUPON_DISPLAY,
        "description": "Favoriten in Buttons mit " + SYMBOLS.STAR + " markieren",
        "default": True
    },
    "highlightNewCouponsInCouponButtonTexts": {
        "category": SettingCategories.COUPON_DISPLAY,
        "description": "Neue Coupons in Buttons mit " + SYMBOLS.NEW + " markieren",
        "default": True
    },
    "highlightVeggieCouponsInCouponButtonTexts": {
        "category": SettingCategories.COUPON_DISPLAY,
        "description": "Veggie Coupons in Buttons mit " + SYMBOLS.BROCCOLI + " markieren",
        "default": True
    },
    "highlightChiliCheeseCouponsInCouponButtonTexts": {
        "category": SettingCategories.COUPON_DISPLAY,
        "description": "Chili Cheese Coupons in Buttons mit " + SYMBOLS.CHILI + " markieren",
        "default": True
    },
    "displayQR": {
        "category": SettingCategories.COUPON_DISPLAY,
        "description": "QR Codes zeigen",
        "default": True
    },
    "displayCouponSortButton": {
        "category": SettingCategories.COUPON_DISPLAY,
        "description": "Coupon sortieren Button zeigen",
        "default": True
    },
    "enableTerminalMode": {
        "category": SettingCategories.COUPON_DISPLAY,
        "description": "Terminal Modus | LangPLU in Buttons zeigen",
        "default": False
    },
    "notifyWhenFavoritesAreBack": {
        "category": SettingCategories.NOTIFICATIONS,
        "description": "Favoriten Benachrichtigungen",
        "default": False
    },
    "notifyWhenNewCouponsAreAvailable": {
        "category": SettingCategories.NOTIFICATIONS,
        "description": "Benachrichtigung bei neuen Coupons",
        "default": False
    },
    "notifyMeAsAdminIfThereAreProblems": {
        "category": SettingCategories.NOTIFICATIONS,
        "description": "Admin Benachrichtigung bei Problemen",
        "default": True
    },
    "notifyOnBotNewsletter": {
        "category": SettingCategories.NOTIFICATIONS,
        "description": "BetterKing TG Newsletter",
        "default": True
    },
    "autoDeleteExpiredFavorites": {
        "category": SettingCategories.MISC,
        "description": "Abgelaufene Favoriten automatisch löschen",
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


def removeDuplicatedCoupons(coupons: Union[List[Coupon], dict]) -> dict:
    couponTitleMapping = getCouponTitleMapping(coupons)
    # Now clean our mapping: Sometimes one product may be available twice with multiple prices -> We want exactly one mapping per title
    couponsWithoutDuplicates = {}
    for normalizedTitle, coupons in couponTitleMapping.items():
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
            elif coupon.getPrice() != firstPrice:
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


def sortCoupons(coupons: Union[list, dict], sortCode: Union[int, CouponSortMode]) -> dict:
    coupons = sortCouponsAsList(coupons, sortCode)
    filteredAndSortedCouponsDict = {}
    for coupon in coupons:
        filteredAndSortedCouponsDict[coupon.id] = coupon
    return filteredAndSortedCouponsDict


def sortCouponsAsList(coupons: Union[list, dict], sortCode: Union[int, CouponSortMode]) -> dict:
    if isinstance(coupons, dict):
        coupons = list(coupons.values())
    if isinstance(sortCode, CouponSortMode):
        sortMode = sortCode
    else:
        sortMode = getSortModeBySortCode(sortCode)
    if sortMode == CouponSortModes.TYPE_MENU_PRICE:
        couponsWithoutFriesAndDrink = []
        couponsWithFriesAndDrink = []
        allContainedCouponTypes = []
        for coupon in coupons:
            if coupon.type not in allContainedCouponTypes:
                allContainedCouponTypes.append(coupon.type)
            if coupon.isContainsFriesAndDrink():
                couponsWithFriesAndDrink.append(coupon)
            else:
                couponsWithoutFriesAndDrink.append(coupon)
        couponsWithoutFriesAndDrink = sortCouponsByPrice(couponsWithoutFriesAndDrink)
        couponsWithFriesAndDrink = sortCouponsByPrice(couponsWithFriesAndDrink)
        # Merge them together again.
        coupons = couponsWithoutFriesAndDrink + couponsWithFriesAndDrink
        # App coupons(source == 0) > Paper coupons
        allContainedCouponTypes.sort()
        # Separate sorted coupons by type
        couponsSeparatedByType = {}
        for couponType in allContainedCouponTypes:
            couponsTmp = list(filter(lambda x: x.type == couponType, coupons))
            couponsSeparatedByType[couponType] = couponsTmp
        # Put our list sorted by type together again -> Sort done
        coupons = []
        for allCouponsOfOneSourceType in couponsSeparatedByType.values():
            coupons += allCouponsOfOneSourceType
    elif sortMode == CouponSortModes.MENU_PRICE:
        couponsWithoutFriesAndDrink = []
        couponsWithFriesAndDrink = []
        for coupon in coupons:
            if coupon.isContainsFriesAndDrink():
                couponsWithFriesAndDrink.append(coupon)
            else:
                couponsWithoutFriesAndDrink.append(coupon)
        couponsWithoutFriesAndDrink = sortCouponsByPrice(couponsWithoutFriesAndDrink)
        couponsWithFriesAndDrink = sortCouponsByPrice(couponsWithFriesAndDrink)
        # Merge them together again.
        coupons = couponsWithoutFriesAndDrink + couponsWithFriesAndDrink
    elif sortMode == CouponSortModes.PRICE:
        coupons = sortCouponsByPrice(coupons)
    elif sortMode == CouponSortModes.PRICE_DESCENDING:
        coupons = sortCouponsByPrice(coupons, descending=True)
    elif sortMode == CouponSortModes.DISCOUNT:
        coupons = sortCouponsByDiscount(coupons)
    elif sortMode == CouponSortModes.DISCOUNT_DESCENDING:
        coupons = sortCouponsByDiscount(coupons, descending=True)
    elif sortMode == CouponSortModes.NEW:
        coupons = sortCouponsByNew(coupons)
    elif sortMode == CouponSortModes.NEW_DESCENDING:
        coupons = sortCouponsByNew(coupons, descending=True)
    else:
        # This should never happen
        logging.warning("Developer mistake!! Unknown sortMode: " + str(sortMode))
    return coupons
