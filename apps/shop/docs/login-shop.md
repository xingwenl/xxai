## 获取图片验证码
curl --url 'http://hua8.bbtree.xyz/hua8-api/code' \
  -H 'Accept: text/plain' \
  -H 'Accept-Language: zh-CN,zh;q=0.9' \
  -H 'Cache-Control: no-cache' \
  -H 'Connection: keep-alive' \
  -H 'Pragma: no-cache' \
  -H 'Referer: http://hua8.bbtree.xyz/login?redirect=/meituan-data/store' \
  -H 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36' \
  --insecure

  ```js
  {
    "msg": "操作成功",
    "img": "Q==",
    "code": 200,
    "captchaEnabled": true,
    "uuid": "124f9201f2c2464a9a91176e6b1074f6"
}
  ```

## 登录
curl --url 'http://hua8.bbtree.xyz/hua8-api/auth/login' \
  -H 'Accept: application/json, text/plain, */*' \
  -H 'Accept-Language: zh-CN,zh;q=0.9' \
  -H 'Cache-Control: no-cache' \
  -H 'Connection: keep-alive' \
  -H 'Content-Type: application/json;charset=UTF-8' \
  -b 'username=admin@weishu; password=OMKvdwaAWwYyrsfHKVgtPyfDy7e8009gy70Gs4u2K2Yg5qXGz5tgYZaBUXaR06eoEbT2oNDXV3sTLq1rLxNrRg==; rememberMe=true' \
  -H 'Origin: http://hua8.bbtree.xyz' \
  -H 'Pragma: no-cache' \
  -H 'Referer: http://hua8.bbtree.xyz/login?redirect=/meituan-data/store' \
  -H 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36' \
  --data-raw '{"username":"admin@weishu","password":"admin123","code":"5","uuid":"c723807bc90043f486c6abc28a1320b0"}' \
  --insecure

```js
{
    "code": 200,
    "msg": null,
    "data": {
        "access_token": "eyJhbGciOiJIUzUxMiJ9.eyJ0ZW5hbnRfaWQiOjIsInVzZXJfaWQiOjEsInVzZXJfa2V5IjoiYTUwMDNkNzItOThiNy00MzNlLTk5YTAtZDMzMjVhNmY3NmJmIiwidXNlcm5hbWUiOiJhZG1pbiJ9.D90ZjOPrD34j2ST6gs-hdj5tlXlWULy7JNm4YvcBHshbBlnLaQLRVyZvDR2sf8Gp1-l8tahryIO4R5LltJLzqg",
        "expires_in": 43200
    }
}

  ```
## 我的用户信息
  curl --url 'http://hua8.bbtree.xyz/hua8-api/system/user/getInfo' \
  -H 'Accept: application/json, text/plain, */*' \
  -H 'Accept-Language: zh-CN,zh;q=0.9' \
  -H 'Authorization: Bearer eyJhbGciOiJIUzUxMiJ9.eyJ0ZW5hbnRfaWQiOjIsInVzZXJfaWQiOjEsInVzZXJfa2V5IjoiYTQ5NDQwOGQtNzU3Mi00MDY3LTllNGUtMWUyZDEwNTgzNTMyIiwidXNlcm5hbWUiOiJhZG1pbiJ9.nwGvnuP7d0eSlOUSLv-2Wt2h3IChyiH09noIzeCQJeHZADWy56gmZzvcvlSlDa5JNK_2hnJKktnyUgbXGVJTTg' \
  -H 'Cache-Control: no-cache' \
  -H 'Connection: keep-alive' \
  -b 'username=admin@weishu; rememberMe=true; password=Ax5fLR1MXh6h3EMHxyL4tPbr/3IkBn6qBTs80bh2rMRFT7twv98rcXcaVK6m/DJIcV3M8iR4yFW2OsH304+N5g==; Admin-Token=eyJhbGciOiJIUzUxMiJ9.eyJ0ZW5hbnRfaWQiOjIsInVzZXJfaWQiOjEsInVzZXJfa2V5IjoiYTQ5NDQwOGQtNzU3Mi00MDY3LTllNGUtMWUyZDEwNTgzNTMyIiwidXNlcm5hbWUiOiJhZG1pbiJ9.nwGvnuP7d0eSlOUSLv-2Wt2h3IChyiH09noIzeCQJeHZADWy56gmZzvcvlSlDa5JNK_2hnJKktnyUgbXGVJTTg; sidebarStatus=1' \
  -H 'Pragma: no-cache' \
  -H 'Referer: http://hua8.bbtree.xyz/meituan-data/store' \
  -H 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36' \
  --insecure

  ```
  {
    "msg": "操作成功",
    "code": 200,
    "permissions": [
        "*:*:*"
    ],
    "roles": [
        "admin"
    ],
    "isDefaultModifyPwd": false,
    "isPasswordExpired": false,
    "user": {
        "createBy": "admin",
        "createTime": "2026-04-07 14:08:45",
        "updateBy": null,
        "updateTime": null,
        "remark": "租户管理员",
        "params": {
            "@type": "java.util.HashMap"
        },
        "userId": 1,
        "deptId": 100,
        "userName": "admin",
        "nickName": "管理员",
        "email": null,
        "phonenumber": null,
        "sex": "1",
        "avatar": null,
        "password": "$2a$10$7JB720yubVSZvUI0rEqK/.VqGOZTH.ulu33dHOiBE8ByOhJIrdAu2",
        "status": "0",
        "delFlag": "0",
        "loginIp": "119.62.115.219",
        "loginDate": "2026-09-02T09:10:02.669+08:00",
        "pwdUpdateDate": "2026-04-07T14:08:45.417+08:00",
        "dept": {
            "createBy": null,
            "createTime": null,
            "updateBy": null,
            "updateTime": null,
            "remark": null,
            "params": {
                "@type": "java.util.HashMap"
            },
            "deptId": 100,
            "parentId": 0,
            "ancestors": "0",
            "deptName": "唯树品牌",
            "orderNum": 0,
            "leader": null,
            "phone": null,
            "email": null,
            "status": "0",
            "delFlag": null,
            "parentName": null,
            "children": []
        },
        "roles": [
            {
                "createBy": null,
                "createTime": null,
                "updateBy": null,
                "updateTime": null,
                "remark": null,
                "params": {
                    "@type": "java.util.HashMap"
                },
                "roleId": 1,
                "roleName": "管理员",
                "roleKey": "admin",
                "roleSort": 1,
                "dataScope": "1",
                "menuCheckStrictly": false,
                "deptCheckStrictly": false,
                "status": "0",
                "delFlag": null,
                "flag": false,
                "menuIds": null,
                "deptIds": null,
                "permissions": null,
                "admin": true
            }
        ],
        "roleNames": null,
        "roleIds": null,
        "postIds": null,
        "roleId": null,
        "admin": true
    }
}
  ```

curl --url 'http://hua8.bbtree.xyz/hua8-api/shop/platform/list' \
  -H 'Accept: application/json, text/plain, */*' \
  -H 'Accept-Language: zh-CN,zh;q=0.9' \
  -H 'Authorization: Bearer eyJhbGciOiJIUzUxMiJ9.eyJ0ZW5hbnRfaWQiOjIsInVzZXJfaWQiOjEsInVzZXJfa2V5IjoiOWYzY2FhNzYtODExNy00MWYxLThmNDktNmJmYTgyMWM5Mjk3IiwidXNlcm5hbWUiOiJhZG1pbiJ9.KLjk5RSVY3oWhaGi6KMcU1afE2qwDQSuLkDPtM3fW75BoJY2M1pLpG09xITvr4xsRcvDL_rIChGn_1q7cCCGbg' \
  -H 'Cache-Control: no-cache' \
  -H 'Connection: keep-alive' \
  -H 'Content-Type: application/json;charset=UTF-8' \
  -b 'username=admin@weishu; password=OMKvdwaAWwYyrsfHKVgtPyfDy7e8009gy70Gs4u2K2Yg5qXGz5tgYZaBUXaR06eoEbT2oNDXV3sTLq1rLxNrRg==; rememberMe=true; Admin-Token=eyJhbGciOiJIUzUxMiJ9.eyJ0ZW5hbnRfaWQiOjIsInVzZXJfaWQiOjEsInVzZXJfa2V5IjoiOWYzY2FhNzYtODExNy00MWYxLThmNDktNmJmYTgyMWM5Mjk3IiwidXNlcm5hbWUiOiJhZG1pbiJ9.KLjk5RSVY3oWhaGi6KMcU1afE2qwDQSuLkDPtM3fW75BoJY2M1pLpG09xITvr4xsRcvDL_rIChGn_1q7cCCGbg' \
  -H 'Origin: http://hua8.bbtree.xyz' \
  -H 'Pragma: no-cache' \
  -H 'Referer: http://hua8.bbtree.xyz/store-manage/platform-store' \
  -H 'User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36' \
  --data-raw '{"page":1,"page_size":20}' \
  --insecure
```js
  {
    "msg": "操作成功",
    "code": 200,
    "data": {
        "list": [
            {
                "id": "2052598884974256130",
                "platformType": "MT",
                "platformStoreId": "25518721",
                "customShopId": null,
                "platformStoreName": "一世感•轻奢花店",
                "logoUrl": "http://p0.meituan.net/business/a05d928038eb2b3aba382c241cbab13d391413.jpg",
                "businessStatus": 1,
                "businessHoursJson": [
                    "00:00-24:00"
                ],
                "acceptPreorderFlag": 1,
                "acceptPreorderStartDays": 0,
                "acceptPreorderDays": 7,
                "feeRate": 10,
                "cooperationTime": "2026-12-16 00:00:00",
                "principalUserId": "48",
                "principalUserName": "花笙",
                "bindStatus": 1,
                "subjectId": "179",
                "subjectName": "有花漾-仪式感花艺",
                "subjectBindType": "AUTO_MATCH",
                "subjectMatchStatus": "MATCHED_EXISTING",
                "subjectLockFlag": 0,
                "remark": "",
                "syncStatus": 2,
                "latestSyncTime": "2026-08-21 09:30:17",
                "authStatus": 1,
                "authError": false,
                "authLimited": false,
                "isOnline": 1,
                "contactPhone": "15892258353",
                "provinceName": null,
                "cityName": null,
                "districtName": null,
                "address": "四川省成都市龙泉驿区大面街道新建路146号附208号",
                "tagIds": [
                    "2052597781532565506",
                    "2052597779565436929"
                ],
                "tagList": [
                    {
                        "id": "2052597781532565506",
                        "name": "有花漾代运营",
                        "desc": null,
                        "catalogueId": "2052597778546221058",
                        "catalogueName": "商品库"
                    },
                    {
                        "id": "2052597779565436929",
                        "name": "托管",
                        "desc": null,
                        "catalogueId": "2052597779225698306",
                        "catalogueName": "收款方式"
                    }
                ]
            },
        ],
        "total": 3677,
        "pages": 184,
        "page": 1,
        "page_size": 20
    }
}
```