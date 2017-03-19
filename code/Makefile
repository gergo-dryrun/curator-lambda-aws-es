publish:
	rm -rf ./publish/curator_lambda/
	mkdir -p ./publish/curator_lambda
	cp -r ./curator_lambda ./publish/
	pip install -t ./publish/curator_lambda -r ./publish/curator_lambda/requirements.txt
	cd ./publish/curator_lambda && zip -r ../curator_lambda.zip .

clean:
	@echo "--> Cleaning pyc files"
	find . -name "*.pyc" -delete
	rm -rf ./publish
	@echo ""
