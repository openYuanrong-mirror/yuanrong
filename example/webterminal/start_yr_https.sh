export LITEBUS_DATA_KEY=6D792D7365637265742D6B65792D666F722D6A77742D64656D6F
export CONTAINER_EP=unix:///var/run/runtime-launcher.sock 
yr start --master --enable_faas_frontend=true -l DEBUG --port_policy FIX --enable_function_scheduler true \
        --enable_meta_service true \
	--ssl_base_path /ws/code/openyuanrong/cert/yr/ \
	--frontend_ssl_enable true \
        --meta_service_ssl_enable true \
	-p services.yaml
	
