# 发布静态文件

# shop
echo "开始发布 shop"
rsync -azhq  -P --delete ./apps/shop/dist/ root@8.153.87.79:/var/www/shop
