# Move Configuration files
```
ln -s ~/docker-openairinterface-epc/oai-docker-conf /etc/oai-docker-conf
```

# eNB Setup
Compile Softmodem:
https://open-cells.com/index.php/2017/08/22/all-in-one-openairinterface-august-22nd/

## Run eNB
```
source oaienv
./cmake_targets/lte_build_oai/build/lte-softmodem -O ~/docker-openairinterface-epc/oai-docker-conf/enb.band7.tm1.25PRB.usrpb210.conf
```

