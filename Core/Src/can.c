/* USER CODE BEGIN Header */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "can.h"

/* USER CODE BEGIN 0 */
#include "usart.h"
/* USER CODE END 0 */

CAN_HandleTypeDef hcan;

/* CAN init function */
void MX_CAN_Init(void)
{

  /* USER CODE BEGIN CAN_Init 0 */
  /* USER CODE END CAN_Init 0 */

  /* USER CODE BEGIN CAN_Init 1 */
  /* USER CODE END CAN_Init 1 */
  hcan.Instance = CAN1;
  hcan.Init.Prescaler = 4;
  hcan.Init.Mode = CAN_MODE_NORMAL;
  hcan.Init.SyncJumpWidth = CAN_SJW_1TQ;
  hcan.Init.TimeSeg1 = CAN_BS1_5TQ;
  hcan.Init.TimeSeg2 = CAN_BS2_2TQ;
  hcan.Init.TimeTriggeredMode = DISABLE;
  hcan.Init.AutoBusOff = ENABLE;
  hcan.Init.AutoWakeUp = DISABLE;
  hcan.Init.AutoRetransmission = DISABLE;
  hcan.Init.ReceiveFifoLocked = DISABLE;
  hcan.Init.TransmitFifoPriority = DISABLE;
  if (HAL_CAN_Init(&hcan) != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN CAN_Init 2 */
  /* USER CODE END CAN_Init 2 */

}

void HAL_CAN_MspInit(CAN_HandleTypeDef* canHandle)
{

  GPIO_InitTypeDef GPIO_InitStruct = {0};
  if(canHandle->Instance==CAN1)
  {
  /* USER CODE BEGIN CAN1_MspInit 0 */
  /* USER CODE END CAN1_MspInit 0 */
    /* CAN1 clock enable */
    __HAL_RCC_CAN1_CLK_ENABLE();

    __HAL_RCC_GPIOA_CLK_ENABLE();
    /**CAN GPIO Configuration
    PA11     ------> CAN_RX
    PA12     ------> CAN_TX
    */
    GPIO_InitStruct.Pin = GPIO_PIN_11;
    GPIO_InitStruct.Mode = GPIO_MODE_INPUT;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

    GPIO_InitStruct.Pin = GPIO_PIN_12;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_HIGH;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);

    /* CAN1 interrupt Init */
    HAL_NVIC_SetPriority(USB_LP_CAN1_RX0_IRQn, 0, 0);
    HAL_NVIC_EnableIRQ(USB_LP_CAN1_RX0_IRQn);
    HAL_NVIC_SetPriority(CAN1_RX1_IRQn, 0, 0);
    HAL_NVIC_EnableIRQ(CAN1_RX1_IRQn);
  /* USER CODE BEGIN CAN1_MspInit 1 */
  /* USER CODE END CAN1_MspInit 1 */
  }
}

void HAL_CAN_MspDeInit(CAN_HandleTypeDef* canHandle)
{

  if(canHandle->Instance==CAN1)
  {
  /* USER CODE BEGIN CAN1_MspDeInit 0 */
  /* USER CODE END CAN1_MspDeInit 0 */
    /* Peripheral clock disable */
    __HAL_RCC_CAN1_CLK_DISABLE();

    /**CAN GPIO Configuration
    PA11     ------> CAN_RX
    PA12     ------> CAN_TX
    */
    HAL_GPIO_DeInit(GPIOA, GPIO_PIN_11|GPIO_PIN_12);

    /* CAN1 interrupt Deinit */
    HAL_NVIC_DisableIRQ(USB_LP_CAN1_RX0_IRQn);
    HAL_NVIC_DisableIRQ(CAN1_RX1_IRQn);
  /* USER CODE BEGIN CAN1_MspDeInit 1 */
  /* USER CODE END CAN1_MspDeInit 1 */
  }
}

/* USER CODE BEGIN 1 */

// 简化版CAN过滤器配置：不过滤任何ID，直接接收所有标准帧
void CAN_Filter_Config(void)
{
  CAN_FilterTypeDef CAN_FilterInitStructure;
  
  // 过滤器组0配置（单CAN外设场景）
  CAN_FilterInitStructure.FilterBank = 0;
  // 掩码模式：全0掩码实现不过滤
  CAN_FilterInitStructure.FilterMode = CAN_FILTERMODE_IDMASK;
  // 32位过滤器（适配标准帧11位ID）
  CAN_FilterInitStructure.FilterScale = CAN_FILTERSCALE_32BIT;
  
  // 过滤器ID和掩码全0 → 接收所有标准帧
  CAN_FilterInitStructure.FilterIdHigh = 0x0000;
  CAN_FilterInitStructure.FilterIdLow = 0x0000;
  CAN_FilterInitStructure.FilterMaskIdHigh = 0x0000;
  CAN_FilterInitStructure.FilterMaskIdLow = 0x0000;
  
  // 接收数据放入FIFO0
  CAN_FilterInitStructure.FilterFIFOAssignment = CAN_RX_FIFO0;
  // 使能过滤器
  CAN_FilterInitStructure.FilterActivation = ENABLE;
  // 单CAN外设无需关心从机配置
  CAN_FilterInitStructure.SlaveStartFilterBank = 14;
  
  // 配置过滤器
  if(HAL_CAN_ConfigFilter(&hcan, &CAN_FilterInitStructure) != HAL_OK)
  {
    Error_Handler();
  }
  
  // 启动CAN外设
  if(HAL_CAN_Start(&hcan) != HAL_OK)
  {
    Error_Handler();
  }
  
  // 使能FIFO0接收中断（有数据时触发）
  if(HAL_CAN_ActivateNotification(&hcan, CAN_IT_RX_FIFO0_MSG_PENDING) != HAL_OK)
  {
    Error_Handler();
  }
}

// （接前面的过滤器配置和接收函数）
uint8_t CAN_Receive_Message(uint32_t *id, uint8_t *data, uint8_t *len)
{
  // 函数体实现
  CAN_RxHeaderTypeDef RxHeader;
  if(id == NULL || data == NULL || len == NULL)
    return 0;
  if(HAL_CAN_GetRxMessage(&hcan, CAN_RX_FIFO0, &RxHeader, data) != HAL_OK)
    return 0;
  *id = RxHeader.StdId;
  *len = RxHeader.DLC;
  return 1;
}

uint8_t CAN_Send_Message(uint32_t id, uint8_t *data, uint8_t len)
{
  CAN_TxHeaderTypeDef TxHeader;
  uint8_t TxMailbox;
  HAL_StatusTypeDef status;
  
  // 1. 参数合法性检查（核心必要检查）
  if(data == NULL || len == 0 || len > 8 || id > 0x7FF)
  {
    return 0; // 无效参数，返回失败
  }
  
  // 2. 配置发送帧头（标准帧配置）
  TxHeader.StdId = id;               // 目标ID
  TxHeader.ExtId = 0;                // 不使用扩展ID
  TxHeader.RTR = CAN_RTR_DATA;       // 数据帧（非远程帧）
  TxHeader.IDE = CAN_ID_STD;         // 标准帧格式（11位ID）
  TxHeader.DLC = len;                // 数据长度（1~8字节）
  TxHeader.TransmitGlobalTime = DISABLE; // 不包含发送时间戳
  
  // 3. 发送数据（带状态判断）
  status = HAL_CAN_AddTxMessage(&hcan, &TxHeader, data, &TxMailbox);
  if(status == HAL_OK)
  {
    return 1; // 发送成功
  }
  else if(status == HAL_BUSY)
  {
    // 发送邮箱已满（可根据需求添加重试逻辑）
    return 0;
  }
  else
  {
    // 其他错误（如外设未启动、参数错误等）
    return 0;
  }
}
// 中断回调函数：收到数据后自动按ID+1回复
void HAL_CAN_RxFifo0MsgPendingCallback(CAN_HandleTypeDef *hcan)
{
  uint32_t rx_id;       // 接收的ID
  uint32_t tx_id;       // 回复的ID（rx_id + 1）
  uint8_t rx_data[8];   // 接收的数据缓冲区
  uint8_t rx_len;       // 接收的数据长度
  
  // 1. 读取接收到的数据
  if(CAN_Receive_Message(&rx_id, rx_data, &rx_len) != 1)
  {
    return; // 接收失败，直接返回
  }
  HAL_UART_Transmit(&huart1, rx_data, rx_len, 0xFFFF);

  // 2. 计算回复ID（原ID+1，限制在标准帧范围内）
  tx_id = rx_id + 1;
  if(tx_id > 0x7FF)    // 标准帧ID最大为0x7FF（11位）
  {
    tx_id = 0x7FF;     // 超出范围时强制设为最大值
  }
  
  // 3. 发送回复（原数据原样返回，长度与接收一致）
  (void)CAN_Send_Message(tx_id, rx_data, rx_len);
  // 此处可根据需要添加发送失败的处理（如重试），简化场景下可忽略
}
/* USER CODE END 1 */
