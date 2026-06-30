export LITEBUS_DATA_KEY=6D792D7365637265742D6B65792D666F722D6A77742D64656D6F
export CONTAINER_EP=unix:///tmp/yr_sessions/runtime-launcher.sock 
yr start --master --enable_faas_frontend=true -l DEBUG --port_policy FIX --enable_function_scheduler true \
        --enable_meta_service true \
	--enable_iam_server true \
	-p services.yaml
	
