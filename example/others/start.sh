yr start --master -l DEBUG -a 172.18.0.4 --port_policy FIX \
	--enable_function_scheduler true \
	--enable_faas_frontend true \
	--enable_meta_service true \
	--ssl_base_path /home/wyc/code/openyuanrong/cert/yr/ \
	--frontend_ssl_enable true \
        --meta_service_ssl_enable true
