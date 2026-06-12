@set Path=%cd%

::EXE file; vbf file path; hash algorithm{SHA256,SHA384,SHA512}; privatekey file with PKCS#1 format{2048, or 3072, or 4096}.
::加研发签名
::VbfSignDev_Geely.exe 6608443838B.vbf SHA256 ReqID_1609v5_661310v1_privateKey2048_dev.pem

::加测试用生产签名
VbfSignTestProd_Geely.exe PNORFlashArea_RTSW_NEW.vbf SHA256 privatekey2048_TestSpecific_Prod.pem

pause
exit