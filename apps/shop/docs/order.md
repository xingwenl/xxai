## 用法
curl --url 'http://hua8.bbtree.xyz/hua8-api/order/manage/orders?page=1&size=20&sortBy=ctime&sortDirection=desc&startTime=1788278400&endTime=1788364799' \
  -H 'Accept: application/json, text/plain, */*' \
  -H 'Accept-Language: zh-CN,zh;q=0.9' \
  -H 'Authorization: Bearer eyJhbGciOiJIUzUxMiJ9.eyJ0ZW5hbnRfaWQiOjIsInVzZXJfaWQiOjEsInVzZXJfa2V5IjoiYTQ5NDQwOGQtNzU3Mi00MDY3LTllNGUtMWUyZDEwNTgzNTMyIiwidXNlcm5hbWUiOiJhZG1pbiJ9.nwGvnuP7d0eSlOUSLv-2Wt2h3IChyiH09noIzeCQJeHZADWy56gmZzvcvlSlDa5JNK_2hnJKktnyUgbXGVJTTg' \
  -H 'Cache-Control: no-cache' \
  -H 'Connection: keep-alive' \
  -b 'username=admin@weishu; rememberMe=true; password=Ax5fLR1MXh6h3EMHxyL4tPbr/3IkBn6qBTs80bh2rMRFT7twv98rcXcaVK6m/DJIcV3M8iR4yFW2OsH304+N5g==; Admin-Token=eyJhbGciOiJIUzUxMiJ9.eyJ0ZW5hbnRfaWQiOjIsInVzZXJfaWQiOjEsInVzZXJfa2V5IjoiYTQ5NDQwOGQtNzU3Mi00MDY3LTllNGUtMWUyZDEwNTgzNTMyIiwidXNlcm5hbWUiOiJhZG1pbiJ9.nwGvnuP7d0eSlOUSLv-2Wt2h3IChyiH09noIzeCQJeHZADWy56gmZzvcvlSlDa5JNK_2hnJKktnyUgbXGVJTTg; sidebarStatus=1' \
  -H 'Pragma: no-cache' \
  -H 'Referer: http://hua8.bbtree.xyz/order/manage' \
  -H 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36' \
  --insecure
## 全部入参数
  {
  "pageNum": 1,
  "pageSize": 20,
  "platformType": "MT",
  "bindStatus": 1,
  "syncStatus": 2,
  "subjectId": 1001,
  "principalUserName": "刘颖",
  "principalUserIds": "1001,1002",
  "withoutPrincipal": true,
  "keyword": "花语鲜花",
  "tagKeyword": "高潜",
  "tagIds": "2052597778890153985,2052597781532565506",
  "withoutTags": true,
  "businessStatus": 1,
  "isOnline": 1,
  "authStatus": 2,
  "authError": true,
  "authLimited": true,
  "platformStoreIds": "MT10001,TB20001",
  "storeIds": "3001,3002"
}
## 返回数据
{
    "msg": "操作成功",
    "code": 200,
    "data": {
        "list": [
            {
                "id": "893262",
                "platform": "MT",
                "app_poi_code": "24524001",
                "wm_poi_name": "格蕾花坊（松山湖店）",
                "day_seq_num": "9",
                "status": 4,
                "ctime": "1788335977",
                "order_id": "3402283352459333476",
                "wm_order_id_view": "3402283352459333476",
                "is_pre_order": false,
                "pre_order": false,
                "delivery_time": "1788339225",
                "delivery_time_left": "1788338805",
                "delivery_time_right": "1788339705",
                "estimate_arrival_time": "1788339225000",
                "order_completed_time": null,
                "logistics_status": null,
                "recipient_name": "吴先生",
                "recipient_phone": "18575194926_8516",
                "recipient_address": "纤织荟 (富康路108号)@#广东省东莞市东莞市大朗镇兴彩原创花式",
                "booker_name": "吴先生",
                "booker_phone": "18575194926_8516",
                "op_desc": "收货人隐私号 18575194926_8516，手机号 157****2731",
                "comment": "",
                "user_order_remark": "",
                "wish": null,
                "wishType": 0,
                "rider_name": null,
                "rider_phone": null,
                "shipper_phone": "",
                "delivery_distance": null,
                "updated": false,
                "brushing": false,
                "remind": false,
                "refund": false,
                "deliveryLate": false,
                "audit_status": 0,
                "force_require_picture": 0,
                "audit_pictures": [],
                "goods": [
                    {
                        "product_id": "yc2604101731",
                        "product_name": "【暖柚春信】教师节鲜花11枝奶油杯玫瑰花郁金香混搭冰淇淋花束生日礼物送女友朋友老师花店配送",
                        "upc": "",
                        "itemNo": "yc2604101731",
                        "sku_name": null,
                        "quantity": 1,
                        "price": "139.00",
                        "poster": "https://img.meituan.net/shangouproductapi/028f4c8e1cba32ef41cdbee145da9488404564.jpg",
                        "refunded": false,
                        "refund_quantity": 0,
                        "refund_amount": null
                    }
                ],
                "refund_type": null,
                "refund_status": null,
                "refund_amount_total": null,
                "after_online_payment": null,
                "refunds": [],
                "productShareFeeChargeByPoi": "16.56",
                "performanceServiceFee": "0.00",
                "actOrderChargeByPoiMoneyCent": "211.00",
                "logisticsFee": "0.00",
                "onlinePayment": "133.00",
                "wmPoiReceiveCent": "121.44",
                "actions": {
                    "confirm": false,
                    "cancel": false,
                    "refund": false,
                    "uploadPicture": true,
                    "brushing": true
                }
            },
            {
                "id": "893257",
                "platform": "MT",
                "app_poi_code": "15853310",
                "wm_poi_name": "花儿朵朵花艺（尖山宽塘店）",
                "day_seq_num": "4",
                "status": 4,
                "ctime": "1788335929",
                "order_id": "4102283353261029605",
                "wm_order_id_view": "4102283353261029605",
                "is_pre_order": false,
                "pre_order": false,
                "delivery_time": "1788340791",
                "delivery_time_left": "0",
                "delivery_time_right": "0",
                "estimate_arrival_time": "1788340791000",
                "order_completed_time": null,
                "logistics_status": null,
                "recipient_name": "凌女士",
                "recipient_phone": "17746891470_9730",
                "recipient_address": "启潮府-7栋 (1101室)@#浙江省嘉兴市海宁市黄湾镇启潮府",
                "booker_name": "凌女士",
                "booker_phone": "17746891470_9730",
                "op_desc": "【卡片内容】：不需要贺卡【备注】：贺卡内容: 祝23岁的你更平和  独立  勇敢  坚定！生日快乐❤️ 不用打电话放1101门口谢谢 收货人隐私号 17746891470_9730，手机号 173****0109",
                "comment": "贺卡内容: 祝23岁的你更平和  独立  勇敢  坚定！生日快乐❤️ 不用打电话放1101门口谢谢",
                "user_order_remark": "贺卡内容: 祝23岁的你更平和  独立  勇敢  坚定！生日快乐❤️ 不用打电话放1101门口谢谢",
                "wish": "不需要贺卡",
                "wishType": 3,
                "rider_name": null,
                "rider_phone": null,
                "shipper_phone": "",
                "delivery_distance": null,
                "updated": false,
                "brushing": false,
                "remind": false,
                "refund": false,
                "deliveryLate": false,
                "audit_status": 0,
                "force_require_picture": 0,
                "audit_pictures": [],
                "goods": [
                    {
                        "product_id": "2410241705",
                        "product_name": "【夜语绮梦】11朵星空紫玫瑰花束生日鲜花生日礼物送女友送闺蜜附近的花店送花上门鲜花免费配送",
                        "upc": "3000146019765",
                        "itemNo": "2410241705",
                        "sku_name": null,
                        "quantity": 1,
                        "price": "59.00",
                        "poster": "http://p0.meituan.net/sgopen/117a08a40754b206713dbaf038646315195655.jpg",
                        "refunded": false,
                        "refund_quantity": 0,
                        "refund_amount": null
                    }
                ],
                "refund_type": null,
                "refund_status": null,
                "refund_amount_total": null,
                "after_online_payment": null,
                "refunds": [],
                "productShareFeeChargeByPoi": "6.49",
                "performanceServiceFee": "0.00",
                "actOrderChargeByPoiMoneyCent": "3.00",
                "logisticsFee": "0.00",
                "onlinePayment": "56.00",
                "wmPoiReceiveCent": "49.51",
                "actions": {
                    "confirm": false,
                    "cancel": false,
                    "refund": false,
                    "uploadPicture": true,
                    "brushing": true
                }
            },
        ],
        "total": "2110",
        "pages": "106",
        "page": "1",
        "page_size": "20"
    }
}

