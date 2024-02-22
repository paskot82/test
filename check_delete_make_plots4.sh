#!/usr/bin/env bash


min_koefficient="0.8"         # коэффициент плота. ниже этого значения будут пересоздаваться.
plots_make="3"                # сколько плотов создавать в каждом разделе (если вписать слово  "max" , то в каждом разделе создастся максимальное количество плотов)
plot_size="80"                # размер плота


compress="0"
key_f="8425ec637fa77684dff47c8156aaec593278ac8ed1a1b024863a264343e7cc3b5f5cd45403913d222802f4425d41b9f8"
key_c="xch1js6dd02v39lan2akh9xwmadnq4lwtdxr7dp8dmpj9ng920v0rxlqjaz55l"




data="$(date +%d.%m.%Y_%H.%M)"
chia_full_log="Chia_Full_Scan_${data}.log"
chia_log="chia-log_$data.log"

clear
echo
echo "              СОЗДАНИЕ  Plots!" | tee -a "$chia_log"
echo
echo "_____________________________________"
echo "     + Проверка процесса плотинга (ps afx)"
echo "     + Поиск/удаление временных файлов"
echo "     + Сканирование... (chia plots check -n 5)"
echo "     + Поиск/удаление плотов с коэффициентом ниже \"$min_koefficient\" (и 0.0 пруфов)"
echo "     + Создание Плотов (в каждом разделе по \"$plots_make\" плотов)"
echo "     + Проверка созданных плотов (пересоздание плохих)"
echo "     + Поиск/удаление временных файлов - 2"
echo "====================================="
echo
echo "
Cоздаст плотов в разделе: $plots_make
мин. коэффициент        : $min_koefficient
размер плота            : $plot_size Gb
compress                : $compress
key_f                   : $key_f
key_c                   : $key_c" | tee -a "$chia_log"
echo
echo "        __________________________________________" | tee -a "$chia_log"
echo "        (можете изменить настройки внутри скрипта)"
echo "        ------------------------------------------"
echo "для продолжения надмите <ENTER> (или жди 10 сек.)"
read -t 10 xxx


IFS=$'\n'

t=0
r=0
p=0
d=0
ddt=0

test_ploting(){

		test_ps=$(ps afx | grep 'chia plotters bladebit' | grep -v 'grep')
	if [ "$test_ps" ];then
		echo
		echo "EXIT!  (Plotters ranning!)" | tee -a "$chia_log"
		echo
		exit 1
	fi
}
test_ploting

clear







start=$(date +%H:%M:%S" ("%d.%m.%Y")")


#######        Поиск и удаление tmp    ################

poisk_tmp(){
	echo
	echo "================================================================" | tee -a "$chia_log"
	echo "$(date +%H:%M:%S" ("%d.%m.%Y")")     + Поиск/удаление временных файлов" | tee -a "$chia_log"
	echo "================================================================" | tee -a "$chia_log"
	echo
#	find /mnt/chia -name "*.plot.tmp" -exec rm -rf {} \;

		for file in $(find /mnt/chia -name "*.plot.tmp")
		do
			ddt=$(($ddt+1))
			rm -rf "${file}"
		done
echo "Удалено временных файлов(*.plot.tmp): $ddt" | tee -a "$chia_log"
}
poisk_tmp
########################################################










########     Сканирование: chia plots check -n 5  ################





scan_t=$(date +%H:%M:%S" ("%d.%m.%Y")")


echo
echo "================================================================" | tee -a "$chia_log"
echo "$(date +%H:%M:%S" ("%d.%m.%Y")")     + Сканирование: \"chia plots check -n 5\"" | tee -a "$chia_log"
echo "================================================================" | tee -a "$chia_log"
echo
echo "Подождите! Идёт Сканирование..."


chia plots check -n 5 &> "${chia_full_log}"

echo "Найденно Плотов в лог-файле (grep Proof) : $(cat ${chia_full_log} | grep 'Proof' | wc -l)" | tee -a "$chia_log"
echo "Найденно Плотов в папках /mnt/chia (find): $(find /mnt/chia -name "*.plot" | wc -l)" | tee -a "$chia_log"

########################################################












#############     проверка коэффициента созданных плотов   ###################
test_plots(){
	IFS=$'\n'
	min_koefficientA=$(echo "$min_koefficient" | sed 's/^0\.//g')  # коэффициент без '0.'
	min_koeff_A="${#min_koefficientA}"                            # количество цифр

	i=0
	for line in $(cat "$1" | grep 'Proofs')
	do
		test_line=$(echo "${line}" | awk '{print $10}' | grep ^'0.' | sed 's/^0\.//g' | sed 's/\.//g')
		zeroProof=$(echo "${line}" | awk '{print $10}' | grep ^'0.0' | sed 's/\.//g')
		path_plot=$(echo "${line}" | awk '{print $12}' | sed -r 's/(.+\.plot).+/\1/')
		
		if [[ "${test_line}" || "$zeroProof" ]];then
#			koeffA=$(echo "${test_line:0:${min_koeff_A}}") # цифр, как у минимума
			min_koefficientB="$test_line"
			
			min_koeff_B="${#test_line}"
#			koeffB=$(echo "${test_line:0:${min_koeff_B}}")




		add_noll() {
			nom=$1              # цифра           (567)
			min_nom=$2        # сколько штук надо (4)
			num_ect="${#nom}" # сколько штук есть (3)
			if [[ "$num_ect" -lt "$min_nom" ]];then
				nom=$(echo "${nom}0")
				add_noll $nom $min_nom
			fi	
		}

			if [ "$min_koeff_B" -gt "$min_koeff_A" ];then
				add_noll $min_koefficientA $min_koeff_B
				min_koefficientA=$nom
			else
				min_koefficientA=$(echo "$min_koefficient" | sed 's/^0\.//g')
			fi


			if [ "$min_koeff_A" -gt "$min_koeff_B" ];then
				add_noll $min_koefficientB $min_koeff_A
				min_koefficientB=$nom
			else
				min_koefficientB="$test_line"
			fi



			if [[ "$min_koefficientB" -lt "$min_koefficientA" || "$zeroProof" ]]; then
				d=$(($d+1))
				rm -rf ${path_plot}
				echo "(0.${test_line} < ${min_koefficient}) | File Deleted : ${path_plot}" | tee -a "$chia_log"
				i=$(($i+1))
				p=$(($p-1))
else
echo "(0.${test_line} >= ${min_koefficient}) | File Ok! : ${path_plot}" | tee -a "$chia_log"
			fi
		fi	
	done
}
##########################################################################################












#######        Поиск и удаление 0.0 пруфов и с коэффициентом ниже  минимума   #########
echo
echo "================================================================" | tee -a "$chia_log"
echo "$(date +%H:%M:%S" ("%d.%m.%Y")")     + Поиск/удаление плотов с коэффициентом ниже \"$min_koefficient\" (и 0.0 пруфов)" | tee -a "$chia_log"
echo "================================================================" | tee -a "$chia_log"
echo 
t_z_profit_f=$(date +%H:%M:%S" ("%d.%m.%Y")")
test_plots "${chia_full_log}"
p=0
i=0
sleep 1
########################################################








############             создание плотов         ###########################
make_plots(){
	test_ploting # проверка плотинга 
	p=$(($p+$1))
	echo "$(date +%H:%M:%S" ("%d.%m.%Y")")    Создаём $1 Plot(s) в разделе: ${2}" | tee -a "$chia_log"
	rm -rf  /tmp/chia_plotters_tmp

chia plotters bladebit cudaplot \
-n $1 \
--compress ${compress} \
-f ${key_f} \
-c ${key_c} \
-d $2 &> /tmp/chia_plotters_tmp


	rm -rf /tmp/chia_check_tmp
	for plot_path in $(cat /tmp/chia_plotters_tmp | grep 'Plot temporary file' | awk '{print $4}' | sed 's/\.tmp//g')
	do
		echo "$(date +%H:%M:%S" ("%d.%m.%Y")") Проверка плота: (chia plots check -n 5 -g ${plot_path})" | tee -a "$chia_log"
		chia plots check -n 5 -g ${plot_path} &> /tmp/chia_check_tmp
		sleep 1
		test_plots /tmp/chia_check_tmp
	done



	if [ "$i" -gt "0" ];then
		echo	
		echo "Deleted $i plots!" | tee -a "$chia_log"	
		echo "Пересоздаём удалённые плоты!" | tee -a "$chia_log"
		sleep 1
		make_plots $i $path_razdel
	fi
}











start_plotting=$(date +%H:%M:%S" ("%d.%m.%Y")")
echo
echo "================================================================" | tee -a "$chia_log"
echo "$(date +%H:%M:%S" ("%d.%m.%Y")")     + Создание Плотов (в каждом разделе по \"$plots_make\" плотов)" | tee -a "$chia_log"
echo "================================================================" | tee -a "$chia_log"
echo

for line in $(df -h | grep chia);do
#for line in $(cat $(dirname $0)/df.txt);do
t=$(($t+1))
plots_makeA=$plots_make

	gb_sort=$(echo "${line}" | awk '{print $4}' | grep -E '[G|T]') 
	razmer=$(echo "${line}" | awk '{print $4}' | sed 's/.$//g')	
	tb=$(echo "${line}" | awk '{print $4}' | grep -E '[T]')

	
	if [ "$tb" ];then
		razmerT=$(echo "$razmer" | sed 's/,/./g')
		razmer=$(echo "${razmerT}*1000" | bc -l | awk -F"." '{print $1}')
	else
		razmer=$(echo "$razmer" | awk -F"," '{print $1}')
	fi
	
	
	
	if [ "$gb_sort" ];then
		path_razdel=$(echo "${line}" | awk '{print $6}')


		if [[ "$razmer" -ge "$plot_size" ]];then
			r=$(($r+1))
			echo; echo;
			echo "$(date +%H:%M:%S" ("%d.%m.%Y")")-----------   Обработка раздела:  ----------" | tee -a "$chia_log"
			echo "$line" | awk '{print $1, $4, $6}' | tee -a "$chia_log"
#			n="$((${razmer}/${plot_size}))"
			n_max="$((${razmer}/${plot_size}))"

			if [ "${plots_makeA}" = "max" ];then
				plots_makeA="$n_max"
			fi
			
			if [ "$plots_makeA" -le  "$n_max" ];then
				n="$plots_makeA"
			else
				n="$n_max"
			fi
						
			echo "размер раздела          : ${razmer} Gb" | tee -a "$chia_log"
			echo "есть место для          : $n_max plots" | tee -a "$chia_log"
			echo "в разделе будет созданно: $n plots" | tee -a "$chia_log"
			echo "--------------------------------------------" | tee -a "$chia_log"
			echo; echo;
			sleep 1
			make_plots $n $path_razdel
		fi
	fi		
done


echo
echo "================================================================" | tee -a "$chia_log"
echo "$(date +%H:%M:%S" ("%d.%m.%Y")")     + Поиск/удаление временных файлов - 2" | tee -a "$chia_log"
echo "================================================================" | tee -a "$chia_log"
echo


test_ploting
t_z_ploting_f=$(date +%H:%M:%S" ("%d.%m.%Y")")
poisk_tmp
#s=$(($p-$d))

echo;echo; echo
echo "======================================" | tee -a "$chia_log"
echo "              Done!" | tee -a "$chia_log"
echo "======================================" | tee -a "$chia_log"
echo
echo "Обработанно всего разделов          : $t" | tee -a "$chia_log"
echo "Найдено подходящих разделов         : $r" | tee -a "$chia_log"
echo "Удалено плотов                      : $d" | tee -a "$chia_log"
echo "Удалено временных файлов(*.plot.tmp): $ddt" | tee -a "$chia_log"
echo "Всего Созданно нормальных плотов    : $p" | tee -a "$chia_log"
echo
echo "=============time==============" | tee -a "$chia_log"
echo "$start - Поиск временных файлов" | tee -a "$chia_log"
echo "$scan_t - Сканирование всех плотов" | tee -a "$chia_log"
echo "$t_z_profit_f - Старт \"Поиска/Удаления\" плохих плотов" | tee -a "$chia_log"
echo "$start_plotting - Создание плотов" | tee -a "$chia_log"
echo "$t_z_ploting_f - Поиск временных файлов" | tee -a "$chia_log"
echo "$(date +%H:%M:%S" ("%d.%m.%Y")") - Finish" | tee -a "$chia_log"
echo "==========================="
echo;echo

exit 0



